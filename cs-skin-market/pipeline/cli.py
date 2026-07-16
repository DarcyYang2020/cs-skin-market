"""
Unified CLI for CS skin market pipeline (v2).
Four-factor model + sector + momentum + events.

Usage:
    python -m pipeline.cli analyze <name> --rarity <r> --source <s> [--discontinued <y>]
    python -m pipeline.cli index
    python -m pipeline.cli sector
    python -m pipeline.cli search <query> [--detail]
    python -m pipeline.cli list
    python -m pipeline.cli history <name>
"""

import argparse
import sys
sys.stdout.reconfigure(encoding="utf-8")
import asyncio
from pathlib import Path

from . import config, db, collector, scorer, reporter, backtest, portfolio, watchlist, regime
from .trend_health import compute_trend_health, trend_health_summary
from .valuation import compute_valuation_grid


def cmd_index(args):
    print("Fetching market index...")
    idx = collector.fetch_market_index()
    if idx is None or idx.value == 0:
        print("[WARN] Could not parse index. Debug output saved to data/_debug_market_index.txt")
        return
    conn = db.get_conn()
    db.save_market_index(conn, idx.value, idx.change_7d, idx.mood)
    conn.commit()
    print(f"  \u7efc\u5408\u6307\u6570: {idx.value:,.2f}")
    print(f"  7\u65e5\u6da8\u8dcc: {idx.change_7d:+.2f}%")
    print(f"  \u5e02\u573a\u60c5\u7eea: {idx.mood}")
    conn.close()


def cmd_sector(args):
    print("Fetching sector flow...")
    sectors = collector.fetch_sector_flow()
    if not sectors:
        print("[WARN] No sector data found. Debug output saved to data/_debug_sector_flow.txt")
        return
    print(f"\nSector Rankings ({len(sectors)} found):\n")
    for s in sectors:
        arrow = "\u2197" if s.change_pct > 0 else ("\u2198" if s.change_pct < 0 else "\u2192")
        print(f"  [{s.rank}] {s.name:<12s} {s.change_pct:+.2f}% {arrow}  ({s.momentum})")


def cmd_search(args):
    print(f"Searching: {args.query}")
    items = asyncio.run(collector_csqaq.search_good_id(args.query, max_results=args.limit))
    if not items:
        print("No results found.")
        return
    print(f"\nFound {len(items)} items:\n")
    for item in items:
        print(f"  {item.name}")
        print(f"    Price: \u00a5{item.price_rmb:,.2f} | Vol: {item.volume_day} | "
              f"Listings: {item.volume_total} | Trend: {item.trend}")
        print()
    if args.detail and items:
        print(f"Fetching detail for: {items[0].name}")
        detail = asyncio.run(collector_csqaq.fetch_item_detail(items[0].name))
        if detail:
            print(f"  Price: \u00a5{detail.price_rmb:,.2f} | Vol: {detail.volume_day}")
            if detail.order_book:
                ob = detail.order_book
                print(f"  OrderBook: sell={ob.sell_count}from \u00a5{ob.lowest_sell:,.2f} | "
                      f"buy={ob.buy_count}at \u00a5{ob.highest_buy:,.2f} | "
                      f"spread={ob.spread_pct:.1f}%")
            if detail.sector:
                print(f"  Sector: {detail.sector}")


def cmd_analyze(args):
    name = args.name
    rarity = args.rarity or "restricted"
    source = args.source or "case"
    is_discontinued = args.discontinued is not None
    discontinued_years = args.discontinued or 0

    # 1. Market index
    print("[1/5] Fetching market index...")
    idx = collector.fetch_market_index()
    if idx is None or idx.value == 0:
        print("[WARN] Market index unavailable, using fallback")
        idx = collector.MarketIndex(value=0, change_7d=0, mood="neutral")

    # 2. Sector flow (NEW)
    print("[2/5] Fetching sector flow...")
    sectors = collector.fetch_sector_flow()

    # 3. Search + detail
    print(f"[3/5] Searching for: {name}")
    items = asyncio.run(collector_csqaq.search_good_id(name, max_results=5))
    if not items:
        print(f"[ERROR] No results for '{name}'")
        return

    item = None
    exact_name = name
    for it in items:
        if it.name == name or name in it.name:
            item = it
            exact_name = it.name
            break
    if item is None:
        item = items[0]
        exact_name = items[0].name

    print(f"[3/5] Fetching detail for: {exact_name}")
    detail = asyncio.run(collector_csqaq.fetch_item_detail(exact_name))
    if detail and (detail.price_rmb > 0 or detail.volume_total > 0):
        item = detail

    price_rmb = item.price_rmb
    volume_day = item.volume_day
    volume_total = item.volume_total
    if volume_day == 0 and volume_total > 0:
        volume_day = max(1, volume_total // 20)
    trend = item.trend or "sideways"
    order_book = item.order_book
    kline_30d = item.kline_30d
    item_sector = item.sector or ""

    # 3.5 Extract historical data from scraped K-line (daily bars)
    price_history = []
    volume_history = []
    supply_history = []
    daily_bars = getattr(item, "_daily_bars", None) or []
    if daily_bars:
        price_history = [b["close"] for b in daily_bars if b.get("close", 0) > 0]
        volume_history = [b.get("volume", 0) for b in daily_bars]
        supply_history = [b.get("in_sale", 0) for b in daily_bars]
        print(f"  Extracted {len(daily_bars)} daily bars from K-line API")
    else:
        # Fallback: use kline_30d for price/volume only
        if kline_30d:
            price_history = [k.close for k in kline_30d if k.close > 0]
            volume_history = [k.volume for k in kline_30d]
        print(f"  Using kline_30d fallback: {len(price_history)} price points")

    # 4. Score (four-factor)
    print("[4/5] Computing four-factor score...")
    score = scorer.score_item(
        rarity=rarity,
        daily_volume=volume_day,
        volume_total=volume_total,
        index_change_7d=idx.change_7d,
        source=source,
        is_discontinued=is_discontinued,
        discontinued_years=discontinued_years,
        order_book=order_book,
        sectors=sectors,
        item_sector=item_sector,
        kline_30d=kline_30d,
        price_history=price_history if price_history else None,
        volume_history=volume_history if volume_history else None,
        supply_history=supply_history if supply_history else None,
    )

    rec = scorer.get_recommendation(
        score.grade, trend, score.momentum_mod, score.liquidity
    )

    print(f"  S:{score.scarcity} V:{score.volume} L:{score.liquidity} M:{score.market}")
    print(f"  Mods: sector={score.sector_mod:+.2f} momentum={score.momentum_mod:+.2f} event={score.event_mod:+.2f}")
    print(f"  Total: {score.total} ({score.grade}) -> {rec}")

    # ---- Trend Health & Valuation Grid (NEW v3) ----
    th_dict = None
    vg_dict = None
    if price_history and len(price_history) >= 8:
        try:
            from .valuation import calc_percentile
            pct_90_val = calc_percentile(price_history[-90:] if len(price_history) >= 90 else price_history, price_history[-1])
            th = compute_trend_health(price_history, volume_history if volume_history else None)
            th_dict = trend_health_summary(th)
            vg = compute_valuation_grid(pct_90_val, th)
            vg_dict = {
                "percentile": vg.percentile,
                "grid_row": vg.grid_row,
                "grid_col": vg.grid_col,
                "grid_label": vg.grid_label,
                "grid_action": vg.grid_action,
                "grid_emoji": vg.grid_emoji,
                "advice": vg.advice,
            }
        except Exception as e:
            print(f"  [warn] trend health: {e}")

    # 5. Report
    print("[5/5] Generating report...")
    weapon, skin, wear = _parse_name_parts(exact_name)
    report_md = reporter.generate_item_report(
        name=exact_name, weapon=weapon, skin=skin, wear=wear,
        score=score, price_rmb=price_rmb,
        volume_day=volume_day, volume_total=volume_total, trend=trend,
        rarity=rarity, source=source,
        is_discontinued=is_discontinued, discontinued_years=discontinued_years,
        index_value=idx.value, index_change_7d=idx.change_7d, index_mood=idx.mood,
        trend_health_dict=th_dict, valuation_grid_dict=vg_dict,
    )

    # Save to DB
    conn = db.get_conn()
    db.save_market_index(conn, idx.value, idx.change_7d, idx.mood)
    item_id = db.upsert_item(
        conn, name=exact_name, weapon=weapon, skin=skin, wear=wear,
        rarity=rarity, source=source,
        is_discontinued=1 if is_discontinued else 0,
        discontinued_years=discontinued_years,
    )
    db.save_price(conn, item_id, price_rmb, volume_day, volume_total)
    db.save_snapshot(
        conn, item_id,
        score_scarcity=score.scarcity, score_volume=score.volume,
        score_market=score.market, total_score=score.total,
        grade=score.grade, recommendation=rec,
        price_rmb=price_rmb, report_md=report_md,
    )
    conn.commit()

    # Save report file
    safe_name = exact_name.replace("|", "_").replace(" ", "_").replace("(", "").replace(")", "")
    report_path = config.DATA_DIR / f"report_{safe_name}.md"
    config.DATA_DIR.mkdir(parents=True, exist_ok=True)
    report_path.write_text(report_md, encoding="utf-8")

    print(f"\n  Report saved: {report_path}")
    print(f"  DB item id: {item_id}")
    print()
    print(report_md)
    conn.close()


def cmd_list(args):
    conn = db.get_conn()
    items = db.list_items(conn)
    if not items:
        print("No items tracked yet.")
        conn.close()
        return
    print(f"\nTracked items ({len(items)}):\n")
    for item in items:
        disc = "Yes" if item['is_discontinued'] else "No"
        print(f"  [{item['id']}] {item['name']}")
        print(f"       Rarity: {item['rarity']} | Source: {item['source']} | "
              f"Discontinued: {disc}")
        print()
    conn.close()


def cmd_history(args):
    conn = db.get_conn()
    item = db.find_item(conn, args.name)
    if not item:
        items = db.list_items(conn)
        for it in items:
            if args.name in it["name"]:
                item = it
                break
    if not item:
        print(f"Item not found: {args.name}")
        conn.close()
        return
    print(f"\n=== {item['name']} ===\n")
    prices = db.get_item_history(conn, item["id"], limit=30)
    if prices:
        print("Recent prices:")
        for p in prices:
            print(f"  {p['date']}  \u00a5{p['price_rmb']:,.2f}  "
                  f"vol: {p['volume_day']}  list: {p['volume_total']}")
    print()
    snapshots = db.get_item_snapshots(conn, item["id"], limit=10)
    if snapshots:
        print("Recent scores:")
        for s in snapshots:
            print(f"  {s['date']}  total: {s['total_score']}  grade: {s['grade']}  "
                  f"rec: {s['recommendation']}")
    conn.close()


def _parse_name_parts(name: str) -> tuple[str, str, str]:
    import re
    weapon, skin, wear = "", "", ""
    parts = name.split("|", 1)
    if len(parts) == 2:
        weapon = parts[0].strip()
        rest = parts[1].strip()
        m = re.search(r'\((.+?)\)$', rest)
        if m:
            wear = m.group(1)
            skin = rest[:rest.rfind("(")].strip()
        else:
            skin = rest
    return weapon, skin, wear




# ---- backtest (P2) ----

# ---- watchlist commands ----
def cmd_regime(args):
    """Display current market regime using daily K-line from csQAQ."""
    idx = collector.fetch_market_index()
    daily_kline = collector.fetch_index_kline()
    if idx and idx.value > 0:
        result = regime.detect_regime(
            index_history=daily_kline,
            current_value=idx.value,
            change_7d=idx.change_7d,
            mood=idx.mood,
        )
    else:
        result = regime.detect_regime(index_history=daily_kline)
    strat = regime.regime_strategy(result)
    print()
    print("=" * 50)
    print("  市场状态分析")
    print("=" * 50)
    print()
    print("  市场:       {}".format(strat["label"]))
    print("  建议仓位:   {}".format(strat["position"]))
    print("  策略:       {}".format(strat["strategy"]))
    print("  信心度:     {}".format(result.confidence))
    if result.index_current > 0:
        print()
        print("  指数:       {:,.2f}".format(result.index_current))
        print("  7日动量:  {:+.1f}%".format(result.momentum_7d))
        print("  30日动量: {:+.1f}%".format(result.momentum_30d))
        print("  30日波动:  {:.1f}%".format(result.volatility_30d))
    print()


def cmd_watchlist(args):
    action = args.action
    conn = db.get_conn()

    if action == "add":
        item_id = db.watchlist_add(
            conn, args.name,
            rarity=args.rarity or "",
            source=args.source or "case",
            is_discontinued=1 if args.discontinued is not None else 0,
            discontinued_years=args.discontinued or 0,
            notes=args.notes or "",
        )
        conn.commit()
        print(f"Added to watchlist: {args.name}")

    elif action == "remove":
        changed = db.watchlist_remove(conn, args.name)
        conn.commit()
        if changed:
            print(f"Removed from watchlist: {args.name}")
        else:
            print(f"Not in watchlist: {args.name}")

    elif action == "edit":
        item = db.watchlist_get(conn, args.name)
        if not item:
            print(f"Not in watchlist: {args.name}")
        else:
            changed = db.watchlist_update(
                conn, args.name,
                rarity=args.rarity or None,
                source=args.source or None,
                is_discontinued=1 if args.discontinued is not None else None,
                discontinued_years=args.discontinued or None,
                notes=args.notes or None,
            )
            if changed:
                print(f"Updated: {args.name}")
            else:
                print(f"No changes for: {args.name}")

    elif action == "list":
        items = db.watchlist_list(conn)
        if not items:
            print("Watchlist is empty.")
        else:
            print(f"\nWatchlist ({len(items)} items):\n")
            print(f"{'#':<4s} {'Name':<45s} {'Rarity':<14s} {'Source':<20s} {'Hold':<6s} {'Added'}")
            print("-" * 96)
            for i, item in enumerate(items, 1):
                name = item["name"][:43]
                rarity = (item["rarity"] or "-")[:12]
                source = (item["source"] or "-")[:18]
                hold_flag = "\u2705" if item["holding"] else "-"
                updated = (item["updated_at"] or "-")[:10]
                print(f"{i:<4d} {name:<45s} {rarity:<14s} {source:<20s} {hold_flag:<6s} {updated}")

            # Holdings summary
            total_buy_cost = db.get_watchlist_holdings_total(conn)
            total_assets_str = db.get_setting(conn, "total_assets", "0")
            try:
                total_assets = float(total_assets_str)
            except (ValueError, TypeError):
                total_assets = 0.0
            position_ratio = (total_buy_cost / total_assets * 100) if total_assets > 0 else 0.0
            print()
            print(f"  \u603b\u8d44\u4ea7: \u00a5{total_assets:,.2f}  |  \u4e70\u5165\u603b\u4ef7: \u00a5{total_buy_cost:,.2f}  |  \u6301\u4ed3\u6bd4\u4f8b: {position_ratio:.1f}%")
            if total_assets == 0:
                print("  \u26a0\ufe0f \u672a\u8bbe\u7f6e\u603b\u8d44\u4ea7\uff0c\u4f7f\u7528 'watchlist assets --set <\u91d1\u989d>' \u8bbe\u7f6e")

    elif action == "report":
        watchlist.view_item_report(args.name)

    elif action == "assets":
        if args.set is not None:
            db.set_setting(conn, "total_assets", args.set)
            print(f"Total assets set to: \u00a5{args.set:,.2f}")
        else:
            total_buy_cost = db.get_watchlist_holdings_total(conn)
            total_assets_str = db.get_setting(conn, "total_assets", "0")
            try:
                total_assets = float(total_assets_str)
            except (ValueError, TypeError):
                total_assets = 0.0
            position_ratio = (total_buy_cost / total_assets * 100) if total_assets > 0 else 0.0
            print()
            print("  \u603b\u8d44\u4ea7:    \u00a5{:,.2f}".format(total_assets))
            print("  \u4e70\u5165\u603b\u4ef7: \u00a5{:,.2f}".format(total_buy_cost))
            print("  \u6301\u4ed3\u6bd4\u4f8b: {:.1f}%".format(position_ratio))
            if total_assets == 0:
                print()
                print("  \u26a0\ufe0f \u672a\u8bbe\u7f6e\u603b\u8d44\u4ea7\uff0c\u4f7f\u7528 --set <\u91d1\u989d> \u8bbe\u7f6e")

    elif action == "scan":
        results = asyncio.run(watchlist.scan_all())
        watchlist.print_scan_summary(results)

    else:
        print(f"Unknown action: {action}")

    conn.close()

def cmd_backtest(args):
    conn = db.get_conn()
    item = db.find_item(conn, args.name)
    if not item:
        for it in db.list_items(conn):
            if args.name in it["name"]:
                item = it
                break
    if not item:
        print("Item not found: " + args.name)
        conn.close()
        return

    snapshots = db.get_item_snapshots(conn, item["id"], limit=365)
    if not snapshots or len(snapshots) < 5:
        print("Not enough snapshots for backtest (need >=5). Run analyze first over multiple days.")
        conn.close()
        return

    prices = [{"date": s["date"], "price": s["price_rmb"], "grade": s["grade"]}
              for s in reversed(snapshots)]

    print("Running backtest on " + item["name"] + " (" + str(len(prices)) + " data points)...")
    result = backtest.run_backtest(prices, strategy="three_factor",
                                   entry_threshold=args.entry or "A",
                                   initial_capital=args.capital or 10000)

    report = backtest.generate_backtest_report(result, item["name"])
    print(report)

    db.save_backtest_result(conn, result.strategy, item["id"],
                            result.start_date, result.end_date,
                            result.initial_capital, result.final_value,
                            result.total_return_pct, result.annualized_return_pct,
                            result.max_drawdown_pct, result.sharpe_ratio,
                            result.win_rate_pct, result.total_trades,
                            result.winning_trades)
    conn.commit()
    conn.close()


# ---- portfolio commands (P2) ----
def cmd_portfolio(args):
    conn = db.get_conn()
    action = args.action

    if action == "add":
        item = db.find_item(conn, args.name)
        if not item:
            print("Item not found. Run analyze first.")
            conn.close()
            return
        pid = db.add_position(conn, item["id"], args.date or _today_str(),
                              args.price, args.qty or 1, args.notes or "")
        conn.commit()
        print("Position added: #" + str(pid) + " " + item["name"] + " @ CNY " + f"{args.price:,.2f}" + " x" + str(args.qty or 1))

    elif action == "check":
        positions = db.list_positions(conn)
        if not positions:
            print("No active positions.")
            conn.close()
            return
        pnl_data = []
        for pos in positions:
            # Get latest price from snapshots
            snaps = db.get_item_snapshots(conn, pos["item_id"], limit=1)
            current_price = snaps[0]["price_rmb"] if snaps else pos["buy_price"]
            pnl = db.get_position_pnl(conn, pos["id"], current_price)
            if pnl:
                pnl_data.append(pnl)
        summary = portfolio.get_portfolio_summary(conn, pnl_data)
        report = portfolio.generate_portfolio_report(summary)
        print(report)

    elif action == "close":
        pos_id = args.id
        db.close_position(conn, pos_id, args.date or _today_str(), args.price)
        conn.commit()
        print("Position #" + str(pos_id) + " closed at CNY " + f"{args.price:,.2f}")

    elif action == "optimize":
        report = portfolio.generate_optimization_report(conn)
        print(report)

    else:
        print("Unknown action: " + action)
    conn.close()


def _today_str():
    from datetime import datetime, timezone, timedelta
    return datetime.now(timezone(timedelta(hours=8))).strftime("%Y-%m-%d")


def main():
    parser = argparse.ArgumentParser(
        description="CS Skin Market Investment Pipeline (v2)",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python -m pipeline.cli index
  python -m pipeline.cli sector
  python -m pipeline.cli search "\u9738\u610f\u5927\u540d" --detail
  python -m pipeline.cli analyze "FN57 | \u9738\u610f\u5927\u540d (\u5d2d\u65b0\u51fa\u5382)" --rarity restricted --source collection --discontinued 10
  python -m pipeline.cli list
  python -m pipeline.cli history "FN57"
""",
    )
    sub = parser.add_subparsers(dest="command")

    sub.add_parser("index", help="Fetch market index")
    sub.add_parser("sector", help="Fetch sector flow rankings")

    p_search = sub.add_parser("search", help="Search items")
    p_search.add_argument("query")
    p_search.add_argument("--limit", type=int, default=5)
    p_search.add_argument("--detail", action="store_true")

    p_analyze = sub.add_parser("analyze", help="Full analysis pipeline")
    p_analyze.add_argument("name")
    p_analyze.add_argument("--rarity")
    p_analyze.add_argument("--source", default="case")
    p_analyze.add_argument("--discontinued", type=float, default=None)

    sub.add_parser("list", help="List tracked items")

    p_history = sub.add_parser("history", help="Price and score history")
    p_history.add_argument("name")

    # P2: backtest
    p_bt = sub.add_parser("backtest", help="Run strategy backtest")
    p_bt.add_argument("name", help="Item name or partial match")
    p_bt.add_argument("--entry", default="A", help="Entry threshold: A or S")
    p_bt.add_argument("--capital", type=float, default=10000)

    
    sub.add_parser("regime", help="Detect market regime")

    # Watchlist management
    p_wl = sub.add_parser("watchlist", help="Manage and scan watchlist")
    p_wl.add_argument("action", choices=["add", "remove", "edit", "list", "scan", "report", "assets"])
    p_wl.add_argument("--name", help="Item name (for add/remove)")
    p_wl.add_argument("--rarity", help="Rarity: consumer/industrial/mil-spec/restricted/classified/covert/contraband")
    p_wl.add_argument("--source", default=None, help="Source: case/collection/discontinued_case")
    p_wl.add_argument("--discontinued", type=float, default=None, help="Years since discontinued")
    p_wl.add_argument("--notes", default="", help="Notes")
    p_wl.add_argument("--set", type=float, default=None, help="Set total assets amount (for assets action)")

# P2: portfolio
    p_pf = sub.add_parser("portfolio", help="Portfolio management")
    p_pf.add_argument("action", choices=["add", "check", "close", "optimize"])
    p_pf.add_argument("--name", help="Item name (for add)")
    p_pf.add_argument("--price", type=float, help="Buy/close price")
    p_pf.add_argument("--qty", type=int, default=1)
    p_pf.add_argument("--date", help="Date YYYY-MM-DD")
    p_pf.add_argument("--notes", default="")
    p_pf.add_argument("--id", type=int, help="Position ID (for close)")

    args = parser.parse_args()

    commands = {
        "index": cmd_index, "sector": cmd_sector, "search": cmd_search,
        "analyze": cmd_analyze, "list": cmd_list, "history": cmd_history,
        "backtest": cmd_backtest, "portfolio": cmd_portfolio, "watchlist": cmd_watchlist, "regime": cmd_regime,
    }
    if args.command in commands:
        commands[args.command](args)
    else:
        parser.print_help()


if __name__ == "__main__":
    main()
