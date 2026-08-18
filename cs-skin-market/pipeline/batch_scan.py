"""Batch scan, discover high-score items, and portfolio advice."""
import html
import logging

from .buy_distance import tranche_plan_text
from .config import TOPUP_EXPECTANCY_STATS
from .portfolio_risk import single_position_exposure
from webapp.render_html import _tpl_env

_log = logging.getLogger("batch_scan")

_EMOJI_PREFIXES = ("🟢 ", "🟡 ", "🟠 ", "🔴 ", "🟤 ", "💥 ")


def signal_guidance(action_label: str = "", expectancy: dict = None, action: str = "") -> dict:
    """Derive signal type + hold guidance from the fusion action label.

    Pure display-layer derivation: never changes any engine decision.
    panic 判定与 item_analysis._is_panic 一致（action_label 含"恐慌"）。
    持有指引依据: 非恐慌段 30d 期望≈0（2026-08-03 扩展回测），恐慌簇 30d 胜率 83%。
    """
    raw = action_label or ""
    for emoji in _EMOJI_PREFIXES:
        raw = raw.replace(emoji, "")
    label = raw.strip()
    if "恐慌" in label:
        sig_type, type_label = "panic", "恐慌共振"
    elif "超跌" in label:
        sig_type, type_label = "oversold", "超跌反弹"
    elif "长持" in label:
        sig_type, type_label = "longhold", "长持结构"
    elif "吸筹" in label:
        sig_type, type_label = "accumulate", "周期吸筹"
    else:
        sig_type, type_label = "base", "低位低估"
    if action and action not in ("buy", "oversold_buy"):
        hold = "未触发买入信号，暂无持有期建议；已持仓按止损止盈/补仓建议管理"
    elif sig_type == "panic":
        hold = ("组合口径统一持有21日（exit 层证伪：时间型早退砍右尾）；"
                "恐慌共振类单品参考14日（30d期望回落），止损建议-25%（恐慌深洗勿收太紧）")
    elif sig_type == "oversold":
        hold = "组合口径统一持有21日；超跌反弹类单品参考14日，止损建议-20%"
    elif sig_type == "longhold":
        hold = ("长持结构类：独立强势长持参考 60~180 日（相对强度/逆市走强证据），"
                "组合口径统一 hold21 模拟；止损建议-20%")
    elif sig_type == "accumulate":
        hold = "周期吸筹类：建议持有21日退出（同低位低估类回测），止损建议-20%"
    else:
        hold = "低位低估类：回测最优持有21日退出，止损建议-20%；固定止盈会截断反弹利润"
    if expectancy and isinstance(expectancy, dict) and expectancy.get("label"):
        type_label = expectancy["label"]
    if sig_type == "panic":
        type_label += "（单事件依赖 2/3）"  # P10（2026-08-17）：事件依赖期望标注，纯展示
    return {"signal_type": sig_type, "type_label": type_label, "hold_guidance": hold}


def market_regime(chg180, chg30, sent=None):
    """市场状态标注（I-1，2026-08-16 起五时期口径，纯展示层，零信号改动）。

    口径 = 大盘五时期（market_context.state_bucket，chg180×chg30 路由，数据挖掘定稿
    market-bucket-alignment.md v2，替代旧六态）+ 贪婪禁入正交覆盖层（sent≤30，任何时期生效）。
    返回 (label, css_class, strategy)。用于大盘仪表盘与批量扫描的市场环境条，
    让使用者一眼看懂当前哪条腿开火。
    """
    from .market_context import state_bucket
    if sent is not None and float(sent) <= 30:
        return ("贪婪禁入", "regime-greedy",
                "市场贪婪（sent≤30）：全腿禁入，逆势抄底期望为负，等情绪转中性/恐惧")
    label = state_bucket(chg180, chg30)
    if label == "P恐慌深跌":
        return ("P 恐慌深跌", "regime-p",
                "大盘30日≤-15%：V型底指纹（回放大盘自身14d 91%/+13.8），"
                "抄底腿可提前分批；吸筹腿待企稳后评估")
    if label == "S1牛市上行":
        return ("S1 牛市上行", "regime-s1",
                "长周期牛+短周期涨：买涨腿（rise_accum/二波）与回调低吸腿正常开火；追高防供给扩张")
    if label == "S2牛市回调":
        return ("S2 牛市回调", "regime-s2",
                "长周期牛+短周期回调：回调买点区——吸筹/深值腿开火（大盘自身30d 57%/+1.0），"
                "买涨腿等 chg30 转正")
    if label == "S3弱市阴跌":
        return ("S3 弱市阴跌", "regime-s3",
                "长周期弱+短周期跌：空仓区（大盘自身全期限负期望），全腿禁开新仓，持仓按止损矩阵管理")
    return ("S4 弱市反弹", "regime-s4",
            "长周期弱+短周期反弹：反抽陷阱（大盘自身30d 28%/-3.0），"
            "新仓仅严格供给收缩+深跌确认，其余标注反抽嫌疑")


def _split_topup_qty(qty):
    """补仓批次数量分配：倒金字塔递减 3:2:1（F-3.7，2026-08-09 回测定稿）。

    总补仓量=持仓量 qty，按 3:2:1 递减分 3 批（首批最深跌幅前最多、越深买得越少），
    最大余数法保证整数和；零量批次自动剔除（小持仓退化为 1~2 批）。
    """
    parts = [3, 2, 1]
    total = sum(parts)
    raw = [qty * p / total for p in parts]
    floors = [int(r) for r in raw]
    rem = qty - sum(floors)
    order = sorted(range(len(parts)), key=lambda i: raw[i] - floors[i], reverse=True)
    for i in range(rem):
        floors[order[i]] += 1
    return [n for n in floors if n > 0]


def _topup_price_plan(avg_cost, qty, current_price, analysis):
    """构建分批补仓价位计划（A方向 2026-08-03，与单品报告 price_zones 同源，纯展示层）。

    返回 (add_positions, entry_zone, avg_cost_after, suggest)；买入区间未放行时前三个为 None，
    suggest 退化为按批数加仓的通用提示。深跌恐慌提前补分支(2026-08-05)复用本函数。
    2026-08-09 (F-3.7)：批次数量改倒金字塔 3:2:1 递减（data/stop_loss_backtest.json
    strategy.topup.rhythm），首批最多、越深越少，总补仓量=持仓量 qty。
    """
    _pz = getattr(analysis, "price_zones", None) or {}
    _entry = _pz.get("entry") or {}
    _cur = _pz.get("current") or current_price
    _e_lo = _entry.get("low", 0) or 0
    _e_hi = _entry.get("high", 0) or 0
    _qs = _split_topup_qty(max(1, int(qty)))
    # 2026-08-18 语义隔离：剥离补仓建议里的"回测补仓点胜率"内嵌数字（拿历史均值当当下胜率）；
    # 补仓点历史证据见 TOPUP_EXPECTANCY_STATS（config，研究区），不进补仓建议文案。
    _base = ""
    if _e_lo > 0 and _e_hi > 0 and _e_hi < _cur:
        _mid = round((_e_lo + _e_hi) / 2, 2)
        _steps = list(zip((_e_hi, _mid, _e_lo), _qs))
        _drops = [round((p - _cur) / _cur * 100, 1) for p, _ in _steps]
        _cost_after = round((avg_cost * qty + sum(p * n for p, n in _steps)) / (qty + sum(n for _, n in _steps)), 2)
        add_positions = [{"price": p, "qty": n, "drop_pct": d} for (p, n), d in zip(_steps, _drops)]
        _part = "、".join(f"批{i+1} ¥{p:.2f} {n}件({d:.1f}%)" for i, ((p, n), d) in enumerate(zip(_steps, _drops)))
        suggest = (f"可分{len(_steps)}批补仓（倒金字塔3:2:1递减，共{qty}件）：{_part}；"
                   f"补满后摊薄成本约¥{_cost_after:.2f}；单批不超过仓位上限15%{_base}")
        return add_positions, {"low": _e_lo, "high": _e_hi}, _cost_after, suggest
    suggest = (f"可分2~3批加仓（倒金字塔3:2:1，单批不超过仓位上限15%）{_base}"
               f"（当前周期结构未放行买入区间，待企稳后更新补仓价位）")
    return None, None, None, suggest


def _stop_loss_plan(avg_cost, qty, current_price, analysis, market_30d_change=None, sold_recent=0):
    """止损评估矩阵（F-3.7，2026-08-09，纯展示层，数据见 data/stop_loss_backtest.json）。

    F-3.14 (2026-08-09) 已执行止损感知（sold_recent = 近30天累计卖出件数）：
    - 「减半止损」以原始量（当前剩余+已卖出）的 50% 为目标上限，已卖出部分扣除，
      不再按当前剩余量的一半重复建议（用户已分批止损后不再「永远减半」）；
    - 已减半（≥50%）后：单品 TH<30（趋势仍恶化）→ 残余升级全止损；否则转观察/不止损。
    触发线：浮亏≥成本线 -15% 触发评估（非直接止损）。状态判定优先级：
      1) 供给扩张（单品在售量30日>+5%）：全止损——结构性派发无反弹预期（60d 深套 41%→1%）
      2) 恐慌深跌（大盘30日≤-15%）：不止损→转补仓评估（60d +1.4% / 90d +7.6%，V型底指纹）
      3) 阴跌中继（-15%~-5%）：减半止损（60d 深套 17.6%→3.4%，全损过激的折中）
      4) 大盘上涨段（>+5%）：不止损（90d 扛+29% vs 损-21.6%，修正旧草案）
      5) 中性（-5%~+5% / 大盘数据缺失）：不止损（90d +51%，控制仓位为主）
    执行参考价 = 触发日现价（成交按市场价记录，滑点口径=成交价÷现价-1）；
    stop_price = 90日关键支撑，仅作挂单参考（避免市价砸穿），不作为成交参考价。
    返回 dict 或 None（未触发评估线）。不改任何引擎信号。
    """
    if avg_cost <= 0 or current_price <= 0:
        return None
    pnl_pct = (current_price - avg_cost) / avg_cost * 100
    if pnl_pct > -15:
        return None
    supply = getattr(analysis, "supply_analysis", None) or {}
    if isinstance(supply, dict):
        s30 = float(supply.get("supply_change_30d") or 0)
    else:
        s30 = float(getattr(supply, "supply_change_30d", 0) or 0)
    m = market_30d_change
    sold_recent = max(0, int(sold_recent or 0))
    total_ref = qty + sold_recent  # 原始参考量 = 当前剩余 + 近30天已卖出
    sold_pct = (sold_recent / total_ref * 100) if total_ref > 0 else 0.0
    _th = getattr(analysis, "trend_health", None) or {}
    th_score = _th.get("score", 50) if isinstance(_th, dict) else getattr(_th, "score", 50)
    low90 = float(getattr(analysis.position, "low_90d", 0) or 0)
    support = low90 if low90 > 0 else current_price
    stop_price = round(min(support, current_price), 2)

    if s30 > 5:
        state, action = "供给扩张", "全止损"
        _sold_note = f"（已执行止损 {sold_recent}/{total_ref} 件）" if sold_recent else ""
        reason = (f"在售量30日扩张{s30:+.0f}%（>5%），结构性派发、无反弹预期{_sold_note}")
        sell_action, ratio_pct, sell_qty = "sell", 100, qty
        evidence = "60d 深套 41%→1%，派发结构无反弹预期"
    elif m is not None and m <= -15:
        state, action = "恐慌深跌", "不止损，转补仓评估"
        reason = f"大盘30日{m:.1f}%（≤-15%）恐慌深跌，V型底指纹，止损反而踏空反弹"
        sell_action, ratio_pct, sell_qty = None, 0, 0
        evidence = "60d +1.4% / 90d +7.6%，V型底 win87% 佐证"
    elif m is not None and -15 < m <= -5:
        if sold_pct < 50:
            state, action = "阴跌中继", "减半止损"
            _target = int(total_ref * 0.5 + 0.5)  # 减半目标 = 原始量50%（四舍五入）
            sell_qty = max(1, min(qty, _target - sold_recent))
            sell_action, ratio_pct = "reduce", round(sell_qty / qty * 100)
            _sold_txt = (f"；已执行止损 {sold_recent}/{total_ref} 件（{sold_pct:.0f}%），"
                         f"本次补足减半差量 {sell_qty} 件") if sold_recent else ""
            reason = (f"大盘30日{m:.1f}%（-15%~-5%）阴跌中继，易继续阴跌，取减半折中{_sold_txt}")
            evidence = (f"60d 深套 17.6%→3.4%；距减半线还差 {max(0, _target - sold_recent)} 件"
                        if sold_recent else "60d 深套 17.6%→3.4%；均-16.3%（全损-21.1/扛单-11.6 折中）")
        elif th_score < 30:
            state, action = "阴跌中继·已减半", "残余升级全止损"
            reason = (f"大盘30日{m:.1f}%阴跌中继，已执行减半止损（{sold_pct:.0f}%）且单品TH={th_score}<30 持续恶化；"
                      f"剩余 {qty} 件为风险残余，升级清仓")
            sell_action, ratio_pct, sell_qty = "sell", 100, qty
            evidence = f"已减半 {sold_pct:.0f}%，TH={th_score}<30 恶化，残余全清"
        else:
            state, action = "阴跌中继·已减半", "观察，不再减半"
            reason = (f"大盘30日{m:.1f}%阴跌中继，但已执行减半止损（{sold_pct:.0f}%），"
                      f"剩余 {qty} 件不再重复减半；观察企稳或跌破关键支撑再评估")
            sell_action, ratio_pct, sell_qty = None, 0, 0
            evidence = f"已减半 {sold_pct:.0f}%，剩余观察；TH={th_score}"
    elif m is not None and m > 5:
        state, action = "大盘上涨段", "不止损"
        reason = f"大盘30日{m:+.1f}%（>+5%）上涨段，持仓随大盘修复概率高"
        sell_action, ratio_pct, sell_qty = None, 0, 0
        evidence = "90d 扛+29% vs 损-21.6%，深套18%"
    else:
        state, action = "中性", "不止损"
        _m_txt = f"{m:+.1f}%" if m is not None else "数据缺失"
        reason = f"大盘30日{_m_txt}（中性），深套概率低，以控制仓位为主"
        sell_action, ratio_pct, sell_qty = None, 0, 0
        evidence = "90d +51%（深套19%，控制仓位为主）"
    return {
        "state": state, "action": action, "reason": reason,
        "pnl_pct": round(pnl_pct, 1),
        "exec_price": current_price,  # 执行参考=现价（成交按市场价，滑点口径基准）
        "stop_price": stop_price if sell_action else None,  # 90日支撑，仅挂单参考
        "ratio_pct": ratio_pct, "sell_action": sell_action, "sell_qty": sell_qty,
        "eval_line": "浮亏≥-15% 触发评估（非直接止损）",
        "evidence": evidence,
        "sold_recent": sold_recent, "total_ref": total_ref, "sold_pct": round(sold_pct, 1),
    }


def _recently_executed_names(days: int = 30):
    """E-2（2026-08-10）近 N 天有执行记录的品名集合：用于批量扫描持仓表「建议未执行」标记。

    纯信息层：仅与 executions 表比对，不改任何建议口径。
    """
    try:
        import datetime
        from . import db as _db
        _d0 = (datetime.date.today() - datetime.timedelta(days=days)).isoformat()
        _conn = _db.get_conn()
        try:
            rows = _conn.execute("SELECT DISTINCT name FROM executions WHERE advice_date >= ?", (_d0,)).fetchall()
            return {r["name"] for r in rows}
        finally:
            _conn.close()
    except Exception:
        return set()


def _is_sellish_advice(pa) -> bool:
    """建议动作是否属「卖出/减仓」类（E-2 判定用）：动作文案或止损矩阵 sell_action 命中即视为需要执行。"""
    if not pa:
        return False
    act = str(pa.get("action") or "")
    if any(k in act for k in ("止损", "止盈", "清仓", "减仓", "卖出")):
        return True
    return bool((pa.get("stop_plan") or {}).get("sell_action"))


def _portfolio_advice(holding, avg_cost, qty, current_price, analysis, market_th=None, sentiment_score=50.0, market_30d_change=None, total_assets=0.0, sold_recent=0):
    """Generate personalized portfolio advice based on cost basis and current position.
    sentiment_score: contrarian 0-100 (0=extreme greed, 100=extreme fear), default neutral.
    补仓分层阈值来自全量日记录回放(2026-08-04, 2025-11-02~2026-07-13, warmup=60, 只读引擎):
      可分批补仓(条件+融合buy): 14d胜率54%/均值+5.4% | 半山腰(25~40): 14d均值≈0 |
      sent<=30(贪婪): 14d均值-2.4% | 大盘未配合(mth<45): 14d均值-1.0%
      2026-08-05 补仓触发优化(24123条日记录回放, 事件级去重): 大盘30日跌幅是区分V型底/阴跌中继的唯一稳健变量
        深跌恐慌提前补(V型底指纹): sent>=80 + 大盘30日跌幅>=15% + pct<=20 + z<=-1 -> 不等TH/大盘确认, 5月V型底 win87%/均+43.7%
        中跌恐慌暂缓(阴跌中继): sent>=80 + 大盘30日跌幅5~15% -> 禁补区(7月中跌 win16%/均-8.3%)
        现行确认链路(TH>=40+大盘TH>=45+融合buy)保持不变
    """
    if not holding or avg_cost <= 0:
        # Non-held: entry advice —— 与单品报告决策同源（fusion_decision），统一口径
        fusion = getattr(analysis, "fusion_decision", {}) or {}
        fusion_action = fusion.get("action", "") if isinstance(fusion, dict) else ""
        label = fusion.get("action_label", "") or ""
        for _em in _EMOJI_PREFIXES:
            label = label.replace(_em, "")
        action_map = {
            "buy": "可分批建仓",
            "oversold_buy": "可分批建仓",
            "watch": "观望等待机会",
            "hold": "持有观察",
            "reduce": "暂不建议入场",
            "sell": "暂不建议入场",
            "avoid": "暂不建议入场",
        }
        action = action_map.get(fusion_action, "观望等待机会")
        risk = "low" if fusion_action in ("buy", "oversold_buy") else ("high" if fusion_action in ("sell", "avoid", "reduce") else "medium")
        detail = fusion.get("action_detail") or ""
        reason = label or "以报告决策为准"
        if label and detail and detail not in label:
            reason = f"{label}：{detail}"
        # 非持仓: 距建仓参考线的距离(2026-08-03), 便于看离买点还有多远
        _pct = getattr(analysis.position, "percentile_90d", 50)
        _z = getattr(analysis.position, "zscore_90d", 0)
        _th_obj = analysis.trend_health or {}
        _th = _th_obj.get("score", 50) if isinstance(_th_obj, dict) else getattr(_th_obj, "score", 50)
        _gd = signal_guidance(fusion.get("action_label", ""), (getattr(analysis, "price_zones", None) or {}).get("expectancy"), fusion_action)
        if fusion_action in ("buy", "oversold_buy"):
            _suggest = "已到建仓区，可分批建仓：" + tranche_plan_text()
            _pz = getattr(analysis, "price_zones", None) or {}
            _entry = _pz.get("entry") or {}
            if _entry.get("low") and _entry.get("high"):
                _suggest += "｜买入区间 ¥{:.2f}~¥{:.2f}".format(_entry["low"], _entry["high"])
            _suggest += "（详见单品报告）"
        else:
            _bd = getattr(analysis, "buy_distance", None) or {}
            if isinstance(_bd, dict) and _bd.get("drop_to_entry_pct") is not None:
                # 价格量化(2026-08-03): 距买入区的下杀幅度，与单品报告同源
                _suggest = _bd.get("summary", "")
                _pz = getattr(analysis, "price_zones", None) or {}
                _entry = _pz.get("entry") or {}
                if _entry.get("low") and _entry.get("high"):
                    _suggest += "｜买入区 ¥{:.2f}~¥{:.2f}".format(_entry["low"], _entry["high"])
                if _bd.get("pct_gap", 0) or _bd.get("z_gap", 0) or _bd.get("th_gap", 0):
                    _conds = []
                    if _bd.get("pct_gap", 0) > 0:
                        _conds.append("估值还差{:.1f}个百分点".format(_bd["pct_gap"]))
                    else:
                        _conds.append("已进低估区")
                    if _bd.get("z_gap", 0) > 0:
                        _conds.append("超跌分还差{:.2f}".format(_bd["z_gap"]))
                    else:
                        _conds.append("已进超跌区")
                    if _bd.get("th_gap", 0) > 0:
                        _conds.append("趋势分还差{:.0f}".format(_bd["th_gap"]))
                    else:
                        _conds.append("趋势分已达标")
                    _suggest += "｜条件：" + "、".join(_conds)
                _suggest += "（详见单品报告）"
            else:
                _gaps = []
                if _pct > 30:
                    _gaps.append(f"pct={_pct:.0f}%(90日位置，越低越便宜)距低估线30%还差{_pct - 30:.0f}pp")
                if _z > -1.5:
                    _gaps.append(f"z={_z:.2f}（参考需≤-1.5）")
                if _th < 35:
                    _gaps.append(f"单品TH={_th:.0f}已入恐慌区(<35)，黄金坑区") 
                elif _th < 55:
                    _gaps.append(f"单品TH={_th:.0f}处于摩擦带(35-54)，需止跌/企稳确认")
                if _gaps:
                    _suggest = "；".join(_gaps) + "（参考线：pct≤30% + z≤-1.5；TH三区：恐慌<35黄金坑 / 35-54摩擦带 / ≥55趋势确认）"
                else:
                    _suggest = f"已接近建仓参考线（pct={_pct:.0f}%、TH={_th:.0f}、z={_z:.2f}），等融合决策确认"
        return {"action": action, "reason": reason, "risk": risk, "fusion_action": fusion_action,
                "suggest": _suggest, "signal_type": _gd["signal_type"], "type_label": _gd["type_label"],
                "hold_guidance": _gd["hold_guidance"],
                "buy_distance": summarize_buy_distance(getattr(analysis, "buy_distance", None) or {})}

    # Held: personalized advice
    cost_total = avg_cost * qty
    market_value = current_price * qty
    pnl_pct = (current_price - avg_cost) / avg_cost * 100 if avg_cost > 0 else 0
    th = analysis.trend_health or {}
    th_score = th.get("score", 50)

    advice = {"cost_price": avg_cost, "current_price": current_price, "qty": qty,
              "pnl_pct": round(pnl_pct, 1), "cost_total": round(cost_total, 2), "market_value": round(market_value, 2)}
    _fusion = getattr(analysis, "fusion_decision", {}) or {}
    _fusion_act = _fusion.get("action", "") if isinstance(_fusion, dict) else ""
    # F-3.7 止损评估矩阵（纯展示层，回测 data/stop_loss_backtest.json）：浮亏≥-15% 触发评估
    _sp = _stop_loss_plan(avg_cost, qty, current_price, analysis, market_30d_change, sold_recent)
    if _sp:
        advice["stop_plan"] = _sp


    if pnl_pct > 20 and th_score < 40:
        advice["action"] = "建议止盈减仓"
        advice["reason"] = f"盈利{pnl_pct:.0f}%且趋势转弱"
        advice["suggest"] = f"可卖出{max(1, qty//2)}件锁定利润"
        advice["reduce_qty"] = max(1, qty // 2)
    elif pnl_pct > 50:
        advice["action"] = "大幅盈利，部分止盈"
        advice["reason"] = f"盈利{pnl_pct:.0f}%，建议卖出1/3~1/2"
        advice["suggest"] = f"可卖出{max(1, qty//3)}~{max(1, qty//2)}件"
        advice["reduce_qty"] = max(1, qty // 3)
    elif pnl_pct < -10:
        # ---- 浮亏持仓：补仓/止损分级（数据验证，见函数docstring）----
        pct = getattr(analysis.position, "percentile_90d", 50)
        z = getattr(analysis.position, "zscore_90d", 0)
        sent = sentiment_score if sentiment_score is not None else 50.0
        # 距离提示(2026-08-03): 各补仓线距当前值差多少, 便于判断离触发还有多远
        advice["gaps"] = {
            "pct": round(max(0.0, pct - 25), 1) if pct > 25 else 0.0,
            "z": round(max(0.0, z + 0.5), 2) if z > -0.5 else 0.0,
            "th": max(0, 40 - int(th_score)) if th_score < 40 else 0,
            "market_th": max(0, 45 - int(market_th)) if market_th is not None and market_th < 45 else 0,
        }
        # 供给扩张禁补（F-3.7，2026-08-09）：在售量30日扩张>5% = 结构性派发（回测60d深套41%→全止损后1%）
        _sup30 = 0.0
        _sup_obj = getattr(analysis, "supply_analysis", None) or {}
        if isinstance(_sup_obj, dict):
            _sup30 = float(_sup_obj.get("supply_change_30d") or 0)
        else:
            _sup30 = float(getattr(_sup_obj, "supply_change_30d", 0) or 0)
        if _sup30 > 5:
            advice["action"] = "禁止补仓"
            advice["reason"] = (f"浮亏{pnl_pct:.0f}%且在售量30日扩张{_sup30:+.0f}%（>5%），"
                                f"供给扩张=结构性派发，补仓无反弹预期")
            advice["suggest"] = (f"在售量30日扩张{_sup30:+.0f}%（>5%）：禁止补仓，按止损建议全止损；"
                                 f"待供给转收缩再评估补仓")
        # 市场极度贪婪：禁止补仓（回测 sent<=30: 30d胜率0%, 均-14%）
        elif sent <= 30:
            advice["action"] = "禁止补仓"
            advice["reason"] = f"浮亏{pnl_pct:.0f}%但市场贪婪(sent={sent:.0f})，逆势抄底期望为负"
            advice["suggest"] = (f"情绪贪婪(sent={sent:.0f}，≤30禁补)，距可补区间还差{max(0, 30 - sent):.0f}分，"
                                 f"等情绪转中性/恐惧再考虑")
        # 深跌恐慌提前补（2026-08-05 V型底指纹）: 恐慌(sent>=80) + 大盘30日跌幅>=15% + 单品深跌
        # 回测(2026-08-05 全量回放): 5月V型底 win87%/均+43.7%（现行确认链路因单品TH未达40错过该段行情）
        # 必须保留 sent>=80：2025-11 深底去掉sent限制后验证失败(均-0.16%)
        elif (market_30d_change is not None and market_30d_change <= -15 and sent >= 80
              and pct <= 20 and z <= -1):
            advice["action"] = "可分批补仓"
            advice["reason"] = (f"浮亏{pnl_pct:.0f}%但恐慌共振(sent={sent:.0f})、大盘30日跌幅{market_30d_change:.1f}%，"
                                f"呈V型底指纹(pct={pct:.0f}%, z={z:.2f})，不等确认提前分批补")
            _adds, _zone, _cost_after, _suggest = _topup_price_plan(avg_cost, qty, current_price, analysis)
            if _adds:
                advice["add_positions"] = _adds
                advice["entry_zone"] = _zone
                advice["avg_cost_after"] = _cost_after
            advice["suggest"] = _suggest
        # 中跌恐慌暂缓（2026-08-05 阴跌中继风险）: 恐慌(sent>=80)但大盘30日跌幅仅5~15%
        # 回测(2026-08-05 全量回放): 7月阴跌中继 win16%/均-8.3%（禁补区，等深跌指纹或企稳确认）
        elif (market_30d_change is not None and -15 < market_30d_change <= -5 and sent >= 80
              and pct <= 20 and z <= -1):
            advice["action"] = "暂缓补仓"
            advice["reason"] = (f"浮亏{pnl_pct:.0f}%、恐慌(sent={sent:.0f})但大盘30日跌幅仅{market_30d_change:.1f}%，"
                                f"处阴跌中继区（5~15%），V型底概率低、易再阴跌")
            advice["suggest"] = (f"当前处中跌恐慌：sent={sent:.0f}、大盘30日跌幅{market_30d_change:.1f}%；"
                                 f"建议等大盘30日跌幅≥15%的深跌指纹，"
                                 f"或等大盘企稳(TH≥45)+融合buy确认再补")
        # E-1（2026-08-10）止损/补仓互斥：止损矩阵判定减半/残余升级止损时，补仓让位于止损。
        # 与「中跌恐慌暂缓」互补——后者仅限 sent>=80 恐慌场景，本互斥覆盖阴跌中继全情绪区间
        elif _sp and _sp.get("sell_action") in ("sell", "reduce") and _sp.get("state") != "供给扩张":
            advice["action"] = "先止损再观察"
            advice["reason"] = (f"浮亏{pnl_pct:.0f}%，止损评估为「{_sp['action']}」（{_sp['state']}），"
                                f"先执行止损释放风险，暂不补仓")
            advice["suggest"] = (f"{_sp['reason']}；补仓需待止损执行完毕、大盘止跌企稳"
                                 f"（TH≥45）且融合决策放行后再评估")
        # 半山腰（pct 25~40）：14d胜率仅28%，不构成补仓点
        elif 25 < pct <= 40:
            advice["action"] = "暂缓补仓"
            advice["reason"] = f"浮亏{pnl_pct:.0f}%但pct={pct:.0f}%处于半山腰，非深度底部"
            advice["suggest"] = (f"pct={pct:.0f}%（90日位置，越低越便宜），距补仓线≤25%还差{pct - 25:.0f}pp；"
                                 f"z={z:.2f}(需≤-0.5)、单品TH={th_score}(需≥40)")
        # 深度低估 + 单品趋势及格 + 大盘配合 + 融合决策放行(buy)：可分批补仓
        # 回测(2026-08-04 全量回放): 条件∩buy 14d胜率54.2%/均值+5.4%; watch 子集-0.3% → 需融合确认
        elif (pct <= 25 and th_score >= 40 and z <= -0.5
              and (market_th is None or market_th >= 45) and _fusion_act == "buy"):
            advice["action"] = "可分批补仓"
            advice["reason"] = f"浮亏{pnl_pct:.0f}%但深度低估(pct={pct:.0f}%, z={z:.2f})，趋势分{th_score}，大盘TH={market_th}，融合决策buy"
            # A方向(2026-08-03) + 价位复用(2026-08-05): 与单品报告 price_zones 同源，深跌恐慌分支共用
            _adds, _zone, _cost_after, _suggest = _topup_price_plan(avg_cost, qty, current_price, analysis)
            if _adds:
                advice["add_positions"] = _adds
                advice["entry_zone"] = _zone
                advice["avg_cost_after"] = _cost_after
            advice["suggest"] = _suggest
        # 深度低估但融合决策未放行：暂缓等确认(回测: watch子集14d均值-0.3%)
        elif pct <= 25 and th_score >= 40 and z <= -0.5 and (market_th is None or market_th >= 45):
            advice["action"] = "暂缓补仓"
            advice["reason"] = f"浮亏{pnl_pct:.0f}%且深度低估(pct={pct:.0f}%)，但融合决策未放行({_fusion_act or '无'})"
            advice["suggest"] = (f"单品条件已满足(pct={pct:.0f}%、z={z:.2f}、单品TH={th_score})，"
                                 f"融合决策={_fusion_act or '无'}，待买点确认再补")
        # 深度低估但大盘未配合：暂缓等共振
        elif pct <= 25 and th_score >= 40 and market_th is not None and market_th < 45:
            advice["action"] = "暂缓补仓"
            advice["reason"] = f"浮亏{pnl_pct:.0f}%且深度低估(pct={pct:.0f}%)，但大盘TH={market_th}仍偏弱"
            advice["suggest"] = (f"单品条件已满足(pct={pct:.0f}%、z={z:.2f}、单品TH={th_score})，"
                                 f"大盘TH={market_th}距45还差{45 - market_th:.0f}分")
        # 趋势走弱：止损是风险预算，先控损
        elif th_score < 30:
            advice["action"] = "趋势走弱，考虑止损"
            advice["reason"] = f"浮亏{pnl_pct:.0f}%且趋势得分{th_score}"
            advice["suggest"] = f"单品TH={th_score}过低(<30)优先控损；待TH回升至≥40且pct≤25%、z≤-0.5再考虑补仓"
        else:
            advice["action"] = "持有观察"
            advice["reason"] = f"浮亏{pnl_pct:.0f}%，未到补仓条件(pct={pct:.0f}%, th={th_score}, 大盘TH={market_th})"
            advice["suggest"] = f"未到补仓线：pct={pct:.0f}%(需≤25)、z={z:.2f}(需≤-0.5)、单品TH={th_score}(需≥40)、大盘TH={market_th}(需≥45)"
    elif abs(pnl_pct) < 10 and th_score >= 50:
        advice["action"] = "继续持有观望"
        advice["reason"] = f"盈亏不大({pnl_pct:.1f}%)且趋势健康({th_score})"
    else:
        advice["action"] = "持有观察"
        advice["reason"] = "建议结合大盘走势决策"
    # B1 单票敞口提示(2026-08-05): (持仓市值+建议补仓额)/总资产 超阈值时提示。
    # 纯展示不拒绝——回测: 单票硬上限误伤 panic 0.3 仓位(收益+54.6%->+24.6%)
    _apply_exposure_hint(advice, market_value, total_assets)
    _gd = signal_guidance(_fusion.get("action_label", "") if isinstance(_fusion, dict) else "",
                          (getattr(analysis, "price_zones", None) or {}).get("expectancy"), _fusion_act)
    advice["signal_type"] = _gd["signal_type"]
    advice["type_label"] = _gd["type_label"]
    advice["hold_guidance"] = _gd["hold_guidance"]
    advice["buy_distance"] = summarize_buy_distance(getattr(analysis, "buy_distance", None) or {})
    return advice

def _apply_exposure_hint(advice, market_value, total_assets):
    """B1 单票敞口提示（纯展示）：(持仓市值 + 建议补仓额) / 总资产 超阈值时在 suggest 追加警示。

    不回绝任何信号——回测(data/b1_risk_validation.json)显示单票硬上限会误伤
    panic 0.3 仓位信号（组合收益 +54.6% 跌至 +24.6%）。
    """
    if not total_assets or total_assets <= 0:
        return None
    adds = advice.get("add_positions") or []
    if not adds:
        # 无实际补仓计划时不提示（避免「削减补仓规模」文案误挂到无补仓建议的场景）
        return None
    add_amount = 0.0
    for _ap in adds:
        add_amount += float(_ap.get("price") or 0) * float(_ap.get("qty") or 0)
    expo = single_position_exposure(market_value, add_amount, total_assets)
    if expo and expo["over"]:
        advice["exposure"] = expo
        _extra = ("｜单票敞口警示：持仓+建议补仓占总资产{:.0f}%（上限{:.0f}%），"
                  "超{:.0f}pp；建议削减本次补仓规模或分批拉长，避免单票过度集中").format(
            expo["after_pct"], expo["cap_pct"], expo["over_pct"])
        advice["suggest"] = (advice.get("suggest") or "") + _extra
    return expo


def summarize_buy_distance(bd):
    """从距买点结果提取表格列摘要（target/gap/进度条），批量扫描与单品报告同源。

    纯展示层：不调用任何信号引擎。
    """
    if not isinstance(bd, dict):
        return None
    try:
        cur = float(bd.get("current_price") or 0)
        target = float(bd.get("target_price") or 0)
    except (TypeError, ValueError):
        return None
    if cur <= 0 or target <= 0:
        return None
    gap = bd.get("gap_pct")
    try:
        gap = round(float(gap), 1) if gap is not None else round((cur - target) / cur * 100, 1)
    except (TypeError, ValueError):
        gap = round((cur - target) / cur * 100, 1)
    try:
        bar = round(float(bd.get("bar_pct") or 100), 0)
    except (TypeError, ValueError):
        bar = 100.0
    return {
        "scenario": bd.get("scenario", ""),
        "scenario_label": bd.get("scenario_label", ""),
        "stage": bd.get("stage"),
        "pct_ok": bool(bd.get("pct_ok")),
        "z_ok": bool(bd.get("z_ok")),
        "th_ok": bool(bd.get("th_ok")),
        "current_price": round(cur, 2),
        "target_price": round(target, 2),
        "gap_pct": gap,
        "bar_pct": bar,
        "pct_gap": bd.get("pct_gap"),
        "z_gap": bd.get("z_gap"),
        "th_gap": bd.get("th_gap"),
        "pct30_price": bd.get("pct30_price"),
        "z15_price": bd.get("z15_price"),
        "low90_price": bd.get("low90_price"),
        "summary": bd.get("summary", ""),
    }


def _pnl_pct(r):
    """持仓盈亏百分比（avg_cost 为 0 时返回 0）。"""
    ac = r.get("avg_cost") or 0
    if ac <= 0:
        return 0.0
    return (float(r.get("price_rmb") or 0) - ac) / ac * 100


def _buy_gap(r):
    """距买点 gap_pct；无距买点数据时给最大值（排最后）。"""
    bd = r.get("buy_distance") or {}
    g = bd.get("gap_pct")
    try:
        return float(g) if g is not None else 999.0
    except (TypeError, ValueError):
        return 999.0


def _proximity_key(r):
    """买点接近度排序键：(优先级, 已达标条件数, 档内剩余距离, gap_pct)。

    优先级 0=已到买点 1=极端超跌(等企稳) 2=下跌寻底 3=其他场景。
    下跌寻底按「已过低估线 + 已过超跌线」条数分层，条数越多越接近买点；
    层内按关键剩余距离升序（未过低估线看估值差、已过低估看超跌差、全过看价格距离）。
    展示层排序，不影响任何引擎信号。
    """
    bd = r.get("buy_distance") or {}
    gap = _buy_gap(r)
    scenario = bd.get("scenario", "")
    if gap <= 0:
        return (0, 0, 0.0, 0.0) if scenario != "extreme" else (1, 0, 0.0, 0.0)
    if scenario == "bottom":
        pct_gap = bd.get("pct_gap")
        z_gap = bd.get("z_gap")
        pct_ok = 1 if (pct_gap is not None and pct_gap <= 0) else 0
        z_ok = 1 if (z_gap is not None and z_gap <= 0) else 0
        n_ok = pct_ok + z_ok
        if n_ok == 0:
            sub = float(pct_gap if pct_gap is not None else 99)
        elif n_ok == 1:
            sub = float(z_gap if z_gap is not None else 99)
        else:
            sub = float(gap)
        return (2, -n_ok, sub, float(gap))
    return (3, 0, float(gap), 0.0)


# ---- 信号层级排序 (2026-08-07): 批量扫描按建议动作分层, 强信号在前、下跌观望最低 ----
# 层级数字越小越靠前; 与 extract_signals 优先级同向(建仓/补仓 > 风控 > 止盈 > 等待 > 观望)
_ACTION_LEVELS = {
    "可分批补仓": 0,
    "可分批建仓": 0,
    "趋势走弱，考虑止损": 1,
    "建议止盈减仓": 2,
    "大幅盈利，部分止盈": 2,
    "禁止补仓": 3,
    "暂缓补仓": 4,
    "继续持有观望": 5,
    "持有观察": 5,
    "暂不建议入场": 6,
    "观望等待机会": 7,   # 下跌观望类, 级别最低
}


def _action_level(r):
    """建议动作 -> 信号层级（0 最高, 越大越靠后; 未识别动作按 9 排最后）。"""
    pa = r.get("portfolio_advice") or {}
    act = (pa.get("action") or "").strip()
    return _ACTION_LEVELS.get(act, 9)


def _level_subkey(r):
    """层级内次级键：
    - 建仓/补仓(0): 买点接近度（已到买点/条件达标多在前）
    - 止损(1): 浮亏越多越前
    - 止盈(2): 盈利越多越前
    - 观望类(>=6): 下跌最严重在前（持仓按浮亏、非持仓按 90 日分位低=深跌）
    - 其余: 距买点剩余距离升序
    """
    level = _action_level(r)
    gap = _buy_gap(r)
    if level == 0:
        return _proximity_key(r)
    if level == 1:
        return _pnl_pct(r)
    if level == 2:
        return -_pnl_pct(r)
    if 6 <= level < 9:  # 明确观望/暂不建议类: 下跌最严重在前（未识别动作 level=9 走通用 gap）
        if r.get("holding"):
            return _pnl_pct(r)
        pct = r.get("percentile_90d")
        try:
            return float(pct) if pct is not None else 50.0
        except (TypeError, ValueError):
            return 50.0
    return gap


def _composite_key(r):
    """综合评分排序键（2026-08-11）：与发现高分品 Top10 同口径，降序。
    旧结果无 composite 时回退 score；两者皆无按0（保持原相对顺序）。"""
    try:
        _c = r.get("composite")
        if _c is None:
            _c = r.get("score") or 0
        return float(_c)
    except (TypeError, ValueError):
        return 0.0


def sort_results(results):
    """批量扫描结果排序：按综合评分降序（2026-08-11，与发现高分品 Top10 同口径：
    数据质量 x 估值折价 x (基础评分+融合决策+趋势加权)。
    持仓/非持仓各自区块内统一口径；展示层排序，不影响任何引擎信号。
    """
    held, unheld = [], []
    for r in results:
        (held if r.get("holding") else unheld).append(r)
    held.sort(key=lambda r: -_composite_key(r))
    unheld.sort(key=lambda r: -_composite_key(r))
    return held + unheld


def extract_signals(results):
    """从批量扫描结果提取值得关注的信号事件（展示层，不改引擎）。

    信号规则（优先级从高到低）:
    - 可分批补仓: 持仓补仓点已确认（正期望门控后）
    - 建议止损: 趋势走弱，风控提示
    - 已到买点: buy_distance.gap_pct <= 0（建仓/补仓参考线已到）
    排序: 补仓 > 止损 > 已到买点，同类型按距买点近优先。
    """
    signals = []
    for r in results:
        if r.get("error"):
            continue
        bd = r.get("buy_distance") or {}
        pa = r.get("portfolio_advice") or {}
        action = (pa.get("action") or "").strip()
        gap = bd.get("gap_pct")
        try:
            gap = float(gap) if gap is not None else None
        except (TypeError, ValueError):
            gap = None
        pnl = pa.get("pnl_pct")
        try:
            pnl = float(pnl) if pnl is not None else None
        except (TypeError, ValueError):
            pnl = None
        sp = pa.get("stop_plan") or {}
        if action == "可分批补仓":
            sig_action = "可分批补仓"
        elif action == "趋势走弱，考虑止损" or sp.get("sell_action"):
            sig_action = "建议止损"
        elif gap is not None and gap <= 0:
            sig_action = "已到买点"
        elif pnl is not None and pnl <= -15:
            sig_action = "接近止损位"
        elif pnl is not None and pnl >= 20:
            sig_action = "浮盈可观·考虑止盈"
        else:
            continue
        signals.append({
            "name": r.get("name", ""),
            "action": sig_action,
            "holding": 1 if r.get("holding") else 0,
            "gap_pct": round(gap, 1) if gap is not None else None,
            "pnl_pct": round(pnl, 1) if pnl is not None else None,
            "suggest": ((pa.get("suggest") or "") + ("｜止损评估：" + str(sp.get("state", "")) if sp.get("sell_action") else ""))[:140],
        })
    _prio = {"可分批补仓": 0, "建议止损": 1, "已到买点": 2,
             "接近止损位": 3, "浮盈可观·考虑止盈": 4}
    signals.sort(key=lambda s: (_prio.get(s["action"], 9),
                                s["gap_pct"] if s["gap_pct"] is not None else 999))
    return signals


def _name_cell(r, name_link):
    """名称单元格：行内展示数据采集时间（2026-08-11，不再标注缓存回退）。"""
    nm = (name_link(r["name"]) if name_link else _esc(r["name"]))
    _ct = (r.get("collected_at") or "").strip()
    if _ct:
        nm += ('<br><span style="font-size:10px;color:var(--text-muted);">采集于 ' + _esc(_ct) + '</span>')
    return nm


def _esc(s):
    """HTML 转义（展示层防注入）。"""
    return html.escape(str(s or ""), quote=True)

# ---- 按建议执行 (P0-2, 2026-08-04): 展示层记账入口, 不改任何信号 ----
_EXEC_ACTION_MAP = {
    "可分批建仓": "buy",
    "可分批补仓": "add",
    "建议止盈减仓": "reduce",
    "大幅盈利，部分止盈": "reduce",
    "趋势走弱，考虑止损": "sell",
}
# 信号动作统一映射（F-1.1, 2026-08-08）：单品报告 / 批量扫描 / exec-modal 共用。
# watch/hold 类信号（回调中·关注、筑底中·观察、恐慌退潮·关注等）默认「观望」，不再硬映射建仓。
FUSION_TO_EXEC = {
    "buy": "buy", "oversold_buy": "buy",
    "watch": "hold", "hold": "hold",
    "reduce": "reduce",
    "sell": "sell", "avoid": "sell",
}
EXEC_ACTION_LABELS = {"buy": "建仓", "add": "补仓", "reduce": "减仓",
                      "sell": "清仓/止损", "hold": "观望"}
_EXEC_BADGE_COLOR = {"buy": "var(--green)", "add": "var(--green)", "hold": "var(--text-muted)",
                     "reduce": "var(--yellow)", "sell": "var(--red)"}
# 批量扫描建议文案 -> 展示动作徽章（观望类也明确显示，不再只有无按钮的困惑）
_ACTION_BADGE = {
    "可分批建仓": "🟢 建仓", "可分批补仓": "🟢 补仓",
    "建议止盈减仓": "🔻 减仓", "大幅盈利，部分止盈": "🔻 减仓",
    "趋势走弱，考虑止损": "🔴 清仓/止损",
    "观望等待机会": "⏸️ 观望", "暂不建议入场": "⏸️ 观望",
    "继续持有观望": "⏸️ 观望", "持有观察": "⏸️ 观望",
    "禁止补仓": "⛔ 禁补", "暂缓补仓": "⏸️ 暂缓补仓",
}


def _action_badge(pa):
    """建议动作徽章：action 文案 -> 统一动作词；未识别一律显示观望。"""
    act = (pa or {}).get("action") or ""
    badge = _ACTION_BADGE.get(act, "⏸️ 观望")
    ea = _EXEC_ACTION_MAP.get(act, "hold")
    return '<span style="font-size:12px;font-weight:700;color:%s;">%s</span>' % (_EXEC_BADGE_COLOR.get(ea, "var(--text-muted)"), badge)



def _exec_btn(name, pa, price):
    """建议动作 -> 执行按钮（build 卡片里的小按钮，带 data-* 供前端弹窗）。

    F-1.3 (2026-08-08): 只给有意义的操作（建仓/补仓/减仓/清仓）出按钮；
    观望类无按钮——没操作不记录，真实相反操作用自选页手动录入。
    F-3.7 (2026-08-09): 持仓浮亏≥15% 时叠加止损按钮（减半/全损），与补仓按钮并列，
    data-qty 预填建议数量；纯展示层、不产生引擎信号。
    """
    act = (pa or {}).get("action") or ""
    ea = _EXEC_ACTION_MAP.get(act)
    btns = []
    if ea:
        btns.append(('<button type="button" class="btn btn-accent btn-sm exec-btn" '
                     'data-name="{n}" data-action="{a}" data-signal="{s}" data-price="{p:.2f}" '
                     'onclick="openExecModal(this)">💼 按建议执行</button>').format(
            n=_esc(name), a=ea, s=_esc(act), p=float(price or 0)))
    sp = (pa or {}).get("stop_plan") or {}
    _sa = sp.get("sell_action")
    if _sa in ("sell", "reduce"):
        _label = "🔴 全止损" if _sa == "sell" else "🔻 减半止损"
        btns.append(('<button type="button" class="btn btn-outline btn-sm exec-btn" '
                     'data-name="{n}" data-action="{a}" data-signal="{s}" data-price="{p:.2f}" data-qty="{q}" '
                     'onclick="openExecModal(this)">{l}</button>').format(
            n=_esc(name), a=_sa, s=_esc("止损评估·" + str(sp.get("state", ""))),
            p=float(sp.get("exec_price") or price or 0), q=int(sp.get("sell_qty") or 1), l=_label))
    return " ".join(btns) if btns else ""


def _bd_cell(bd):
    """距买点表格单元格：目标价 + 下杀幅度 + 微型进度条 + 条件达标徽标 + 场景标签。"""
    if not bd:
        return '<span style="font-size:11px;color:var(--text-muted);">—</span>'
    gap = bd.get("gap_pct")
    bar = min(100.0, max(0.0, float(bd.get("bar_pct") or 0)))
    at = gap is not None and gap <= 0
    color = "var(--green)" if at else "var(--yellow)"
    gap_txt = "已到" if at else "还差 {:.1f}%".format(gap)
    # 条件达标徽标（下跌寻底场景）：估值线 / 超跌线 / 趋势分，直观展示接近程度
    conds = []
    if bd.get("scenario") == "bottom":
        for label, key, fmt in (("估值", "pct_gap", "{:.1f}个百分点"),
                                ("超跌", "z_gap", "{:.2f}"),
                                ("趋势分", "th_gap", "{:.0f}分")):
            v = bd.get(key)
            if v is None:
                continue
            try:
                v = float(v)
            except (TypeError, ValueError):
                continue
            if v <= 0:
                conds.append('<span style="padding:1px 5px;border-radius:3px;background:rgba(5,150,105,0.12);color:var(--green);font-size:10px;">'
                             + label + " ✓</span>")
            else:
                conds.append('<span style="padding:1px 5px;border-radius:3px;background:rgba(245,158,11,0.15);color:var(--yellow);font-size:10px;">'
                             + label + " 差" + fmt.format(v) + "</span>")
    cond_row = ('<div style="margin-top:3px;display:flex;gap:3px;flex-wrap:wrap;">'
                + "".join(conds) + "</div>") if conds else ""
    return ('<span style="font-size:11px;color:var(--text-muted);">'
            + bd.get("scenario_label", "") + "</span><br>"
            + '<b style="color:{c};">¥{t:.2f}</b>'.format(c=color, t=bd.get("target_price") or 0)
            + ' <span style="color:{c};font-size:11px;">（{g}）</span>'.format(c=color, g=gap_txt)
            + '<div style="height:5px;background:rgba(15,23,42,0.06);border-radius:3px;margin-top:3px;overflow:hidden;">'
            + '<div style="height:100%;width:{b:.0f}%;background:linear-gradient(90deg,var(--blue),var(--green));"></div></div>'.format(b=bar)
            + cond_row)


def _score_badge(r, g):
    """评分单元格：评级徽章 + 综合评分（2026-08-11，排序口径与 Top10 高分品一致）。"""
    _comp = r.get("composite")
    try:
        _comp_txt = "{:.1f}".format(float(_comp)) if _comp is not None else ""
    except (TypeError, ValueError):
        _comp_txt = ""
    _badge = '<span class="badge badge-' + g + '">' + _esc(str(r.get("grade", "?"))) + "</span>"
    if _comp_txt:
        _badge += '<br><span style="font-size:11px;font-weight:600;color:var(--text-primary);">综合 ' + _comp_txt + '</span>'
    return _badge


def build_scan_html(results, total, now_str="", name_link=None):
    """批量扫描结果 → Jinja（汇总统计 + 持仓/关注表格 + 距买点列 + 行级强制刷新）。

    展示层函数：不调用任何信号引擎。页面结构在 templates/partials/scan_html.html；
    单元格组件（距买点/评分/刷新按钮/名称，含 JS 转义与业务逻辑）保留 Python。
    2026-08-11：移除市场环境卡片（持仓管理页精简）；刷新改为每行单品级（F-3.21）。
    """
    held = [r for r in results if r.get("holding") and r.get("error") is None]
    unheld = [r for r in results if not r.get("holding") and r.get("error") is None]
    errors = [r for r in results if r.get("error")]
    n_at_buy = sum(1 for r in results if (r.get("buy_distance") or {}).get("gap_pct") is not None
                   and float((r.get("buy_distance") or {}).get("gap_pct", 99)) <= 0)
    n_near = sum(1 for r in results if 0 < float((r.get("buy_distance") or {}).get("gap_pct", 99)) <= 5)
    n_loss = sum(1 for r in held if _pnl_pct(r) < 0)
    n_ok = len(results) - len(errors)
    stats = []
    if n_at_buy:
        stats.append(str(n_at_buy) + " 个已到买点")
    if n_near:
        stats.append(str(n_near) + " 个接近买点（≤5%）")
    if n_loss:
        stats.append(str(n_loss) + " 个持仓浮亏")
    stats_line = " · ".join(stats) if stats else ""

    def _refresh_btn(r):
        nm = _esc(str(r.get("name") or ""))
        return ('<button type="button" class="btn btn-xs btn-outline" data-name="' + nm + '" '
                'onclick="refreshScanItem(this)" title="强制联网重采该品并重算评分">⚡ 刷新</button>')

    def _held_row(r):
        pnl_pct = _pnl_pct(r)
        g = (r.get("grade") or "?").lower()
        pnl_c = "green" if pnl_pct > 5 else ("red" if pnl_pct < -5 else "")
        return {"name_cell": _name_cell(r, name_link),
                "avg_cost": float(r.get("avg_cost") or 0), "price": float(r.get("price_rmb") or 0),
                "pnl_pct": pnl_pct, "pnl_cls": pnl_c,
                "badge": _score_badge(r, g),
                "bd_cell": _bd_cell(r.get("buy_distance")),
                "refresh_btn": _refresh_btn(r)}

    def _unheld_row(r):
        g = (r.get("grade") or "?").lower()
        return {"name_cell": _name_cell(r, name_link),
                "price": float(r.get("price_rmb") or 0),
                "badge": _score_badge(r, g),
                "valuation_tier": _esc(str(r.get("valuation_tier", "?"))),
                "pct": float(r.get("percentile_90d", 50) or 50),
                "bd_cell": _bd_cell(r.get("buy_distance")),
                "refresh_btn": _refresh_btn(r)}

    return _tpl_env.get_template("partials/scan_html.html").render(
        now_str=now_str, n_ok=n_ok, total=total, stats_line=stats_line,
        held=[_held_row(r) for r in held], unheld=[_unheld_row(r) for r in unheld],
        errors=[{"name": _esc(e["name"]), "error": _esc(e.get("error", ""))} for e in errors])
