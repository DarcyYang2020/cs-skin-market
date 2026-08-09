"""Batch scan, discover high-score items, and portfolio advice."""
import html
import logging

from .buy_distance import tranche_plan_text
from .config import TOPUP_EXPECTANCY_STATS, PORTFOLIO_CAP_CONCURRENT
from .portfolio_risk import single_position_exposure

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
    elif "吸筹" in label:
        sig_type, type_label = "accumulate", "周期吸筹"
    else:
        sig_type, type_label = "base", "低位低估"
    if action and action not in ("buy", "oversold_buy"):
        hold = "未触发买入信号，暂无持有期建议；已持仓按止损止盈/补仓建议管理"
    elif sig_type == "panic":
        hold = "恐慌共振类：回测最优持有14日退出（30d期望回落），止损建议-25%（恐慌深洗勿收太紧）"
    elif sig_type == "oversold":
        hold = "超跌反弹类：默认14日退出，止损建议-20%"
    elif sig_type == "accumulate":
        hold = "周期吸筹类：建议持有21日退出（同低位低估类回测），止损建议-20%"
    else:
        hold = "低位低估类：回测最优持有21日退出，止损建议-20%；固定止盈会截断反弹利润"
    if expectancy and isinstance(expectancy, dict) and expectancy.get("label"):
        type_label = expectancy["label"]
    return {"signal_type": sig_type, "type_label": type_label, "hold_guidance": hold}


def market_regime(sent, chg30, th=None):
    """市场状态标注（I-1，2026-08-06，纯展示层，零信号改动）。

    口径 = 统一状态桶（market_context.state_bucket，引擎口径 sent>=75 判恐慌，阶段4 对齐
    engine-unified §3.3；补仓引擎的 80 分恐慌阈值是回测参数，不在此函数内）。
    返回 (label, css_class, strategy)。用于大盘仪表盘与批量扫描的市场环境条，
    让使用者一眼看懂当前哪条腿开火。
    """
    from .market_context import state_bucket
    label = state_bucket(sent, th, chg30)
    if label == "贪婪禁入":
        return ("贪婪禁入", "regime-greedy",
                "市场贪婪（sent≤30）：全腿禁入，逆势抄底期望为负，等情绪转中性/恐惧")
    if label == "V型底区":
        return ("V型底区", "regime-vbottom",
                "恐慌+深跌（大盘30日≤-15%）：V型底指纹，抄底腿可提前分批；吸筹腿待企稳后评估")
    if label == "阴跌中继区":
        return ("阴跌中继区", "regime-risky",
                "恐慌+中跌（大盘30日 -15~-5%）：阴跌中继风险（回测7月14d均-8.3%），"
                "抄底腿防御——等深跌指纹或企稳确认；吸筹腿观望（需单品在售量收缩+价格平稳方可触发）")
    if label == "恐慌浅跌":
        return ("恐慌浅跌", "regime-panic",
                "恐慌但大盘30日跌幅<5%：抄底腿正常开火，吸筹腿观望（需单品供给收缩+价格平稳）")
    if label == "中性企稳":
        return ("中性企稳", "regime-ok",
                "非恐慌+大盘TH≥45：抄底+吸筹双腿可开火（趋势腿需价格平稳+供给收缩）")
    return ("弱市观望", "regime-weak",
            "非恐慌但大盘TH<45：抄底腿等待企稳，吸筹腿受门控（禁贪婪弱TH共振）")


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
    _stats = TOPUP_EXPECTANCY_STATS["topup_ok"]
    _base = f"（回测：补仓点14d胜率{_stats['win14']:.0f}%、均值+{_stats['avg14']:.1f}%"
    if _stats.get("events"):
        _base += f"、{_stats['events']}次独立事件"
    _base += "）"
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


def _stop_loss_plan(avg_cost, qty, current_price, analysis, market_30d_change=None):
    """止损评估矩阵（F-3.7，2026-08-09，纯展示层，数据见 data/stop_loss_backtest.json）。

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
    low90 = float(getattr(analysis.position, "low_90d", 0) or 0)
    support = low90 if low90 > 0 else current_price
    stop_price = round(min(support, current_price), 2)

    if s30 > 5:
        state, action = "供给扩张", "全止损"
        reason = (f"在售量30日扩张{s30:+.0f}%（>5%），结构性派发、无反弹预期；"
                  f"回测60d深套率41%→全止损后降至1%")
        sell_action, ratio_pct, sell_qty = "sell", 100, qty
        evidence = "60d 深套 41%→1%，派发结构无反弹预期"
    elif m is not None and m <= -15:
        state, action = "恐慌深跌", "不止损，转补仓评估"
        reason = (f"大盘30日{m:.1f}%（≤-15%）恐慌深跌，V型底指纹；"
                  f"回测60d +1.4% / 90d +7.6%，止损反而踏空反弹")
        sell_action, ratio_pct, sell_qty = None, 0, 0
        evidence = "60d +1.4% / 90d +7.6%，V型底 win87% 佐证"
    elif m is not None and -15 < m <= -5:
        state, action = "阴跌中继", "减半止损"
        reason = (f"大盘30日{m:.1f}%（-15%~-5%）阴跌中继，易继续阴跌；"
                  f"回测60d深套率17.6%→减半后3.4%，全损过激（-21.1%）取折中")
        sell_action, ratio_pct, sell_qty = "reduce", 50, max(1, qty // 2)
        evidence = "60d 深套 17.6%→3.4%；均-16.3%（全损-21.1/扛单-11.6 折中）"
    elif m is not None and m > 5:
        state, action = "大盘上涨段", "不止损"
        reason = (f"大盘30日{m:+.1f}%（>+5%）上涨段，持仓随大盘修复概率高；"
                  f"回测90d扛单+29% vs 止损-21.6%")
        sell_action, ratio_pct, sell_qty = None, 0, 0
        evidence = "90d 扛+29% vs 损-21.6%，深套18%"
    else:
        state, action = "中性", "不止损"
        _m_txt = f"{m:+.1f}%" if m is not None else "数据缺失"
        reason = (f"大盘30日{_m_txt}（中性），深套概率低；"
                  f"回测90d +51%，以控制仓位为主")
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
    }


def _portfolio_advice(holding, avg_cost, qty, current_price, analysis, market_th=None, sentiment_score=50.0, market_30d_change=None, total_assets=0.0):
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
    _sp = _stop_loss_plan(avg_cost, qty, current_price, analysis, market_30d_change)
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
            advice["suggest"] = (f"在售量30日扩张{_sup30:+.0f}%（>5%）：回测60d深套率41%→全止损后降至1%，"
                                 f"禁止补仓，按止损建议全止损；待供给转收缩再评估补仓")
        # 市场极度贪婪：禁止补仓（回测 sent<=30: 30d胜率0%, 均-14%）
        elif sent <= 30:
            advice["action"] = "禁止补仓"
            advice["reason"] = f"浮亏{pnl_pct:.0f}%但市场贪婪(sent={sent:.0f})，逆势抄底期望为负"
            advice["suggest"] = (f"情绪贪婪(sent={sent:.0f}，≤30禁补)，距可补区间还差{max(0, 30 - sent):.0f}分，"
                                 f"等情绪转中性/恐惧再考虑（回测：贪婪期补仓14d均值{TOPUP_EXPECTANCY_STATS['greedy']['avg14']:+.1f}%）")
        # 深跌恐慌提前补（2026-08-05 V型底指纹）: 恐慌(sent>=80) + 大盘30日跌幅>=15% + 单品深跌
        # 回测(2026-08-05 全量回放): 5月V型底 win87%/均+43.7%（现行确认链路因单品TH未达40错过该段行情）
        # 必须保留 sent>=80：2025-11 深底去掉sent限制后验证失败(均-0.16%)
        elif (market_30d_change is not None and market_30d_change <= -15 and sent >= 80
              and pct <= 20 and z <= -1):
            advice["action"] = "可分批补仓"
            advice["reason"] = (f"浮亏{pnl_pct:.0f}%但恐慌共振(sent={sent:.0f})、大盘30日跌幅{market_30d_change:.1f}%，"
                                f"呈V型底指纹(pct={pct:.0f}%, z={z:.2f})，不等确认提前分批补"
                                f"（回测：深跌恐慌5月V型底14d胜率87%/均+43.7%）")
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
                                f"处阴跌中继区（5~15%），V型底概率低、易再阴跌"
                                f"（回测：中跌恐慌14d胜率16%/均-8.3%）")
            advice["suggest"] = (f"当前处中跌恐慌：sent={sent:.0f}、大盘30日跌幅{market_30d_change:.1f}%；"
                                 f"历史同场景易阴跌（14d均-8.3%），建议等大盘30日跌幅≥15%的深跌指纹，"
                                 f"或等大盘企稳(TH≥45)+融合buy确认再补")
        # 半山腰（pct 25~40）：14d胜率仅28%，不构成补仓点
        elif 25 < pct <= 40:
            advice["action"] = "暂缓补仓"
            advice["reason"] = f"浮亏{pnl_pct:.0f}%但pct={pct:.0f}%处于半山腰，非深度底部"
            advice["suggest"] = (f"pct={pct:.0f}%（90日位置，越低越便宜），距补仓线≤25%还差{pct - 25:.0f}pp；"
                                 f"z={z:.2f}(需≤-0.5)、单品TH={th_score}(需≥40)（回测：半山腰14d均值≈0，暂缓）")
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
                                 f"融合决策={_fusion_act or '无'}，待买点确认再补"
                                 f"（回测：未确认14d均值{TOPUP_EXPECTANCY_STATS['topup_wait']['avg14']:+.1f}%）")
        # 深度低估但大盘未配合：暂缓等共振
        elif pct <= 25 and th_score >= 40 and market_th is not None and market_th < 45:
            advice["action"] = "暂缓补仓"
            advice["reason"] = f"浮亏{pnl_pct:.0f}%且深度低估(pct={pct:.0f}%)，但大盘TH={market_th}仍偏弱"
            advice["suggest"] = (f"单品条件已满足(pct={pct:.0f}%、z={z:.2f}、单品TH={th_score})，"
                                 f"大盘TH={market_th}距45还差{45 - market_th:.0f}分"
                                 f"（回测：大盘未配合14d均值{TOPUP_EXPECTANCY_STATS['mkt_weak']['avg14']:+.1f}%）")
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


def sort_results(results):
    """批量扫描结果排序：先按建议动作信号层级（可建仓/补仓 > 止损 > 止盈 > 等待 > 下跌观望最低），
    层级内按对应度量排序（观望类按下跌最严重：持仓浮亏大在前、非持仓深跌在前）。
    持仓/非持仓各自区块内统一口径；展示层排序，不影响任何引擎信号。
    """
    held, unheld = [], []
    for r in results:
        (held if r.get("holding") else unheld).append(r)
    held.sort(key=lambda r: (_action_level(r), _level_subkey(r)))
    unheld.sort(key=lambda r: (_action_level(r), _level_subkey(r)))
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


def build_scan_html(results, total, market_ctx=None, now_str="", name_link=None, risk_ctx=None):
    """批量扫描结果 → HTML（市场条 + 汇总统计 + 持仓/关注表格 + 距买点列）。

    展示层函数：不调用任何信号引擎。
    """
    market_ctx = market_ctx or {}
    held = [r for r in results if r.get("holding") and r.get("error") is None]
    unheld = [r for r in results if not r.get("holding") and r.get("error") is None]
    errors = [r for r in results if r.get("error")]
    n_at_buy = sum(1 for r in results if (r.get("buy_distance") or {}).get("gap_pct") is not None
                   and float((r.get("buy_distance") or {}).get("gap_pct", 99)) <= 0)
    n_near = sum(1 for r in results if 0 < float((r.get("buy_distance") or {}).get("gap_pct", 99)) <= 5)
    n_loss = sum(1 for r in held if _pnl_pct(r) < 0)
    n_ok = len(results) - len(errors)
    h = []
    h.append('<div class="card" id="batch-result" style="margin-bottom:16px;">')
    h.append('<div class="card-header" style="justify-content:space-between;"><span class="card-title">批量扫描完成</span>')
    h.append('<span style="font-size:13px;color:var(--text-muted);">' + _esc(now_str) + " | 成功 " + str(n_ok) + "/" + str(total) + " | 刷新后仍保留</span></div></div>")
    # 市场环境条
    th = market_ctx.get("th")
    sent = market_ctx.get("sentiment")
    cycle = market_ctx.get("cycle") or "unknown"
    idxv = market_ctx.get("index")
    th_txt = "{:.0f}".format(th) if th is not None else "?"
    sent_txt = "{:.0f}".format(sent) if sent is not None else "?"
    mood = "恐惧" if (sent is not None and sent >= 60) else ("贪婪" if (sent is not None and sent <= 30) else "中性")
    # I-1 市场状态标注(2026-08-06): V型底区/阴跌中继区等, 纯展示层
    _regime_label, _regime_cls, _regime_strategy = market_regime(sent, market_ctx.get("chg30"), th)
    h.append('<div class="card" style="margin-bottom:16px;"><div class="card-header"><span class="card-title">市场环境</span></div>'
             '<div style="padding:10px 14px;font-size:13px;color:var(--text-secondary);">'
             + ("指数 " + _esc("{:.0f}".format(idxv)) + " ｜" if idxv else "") + " 大盘TH=" + th_txt + " ｜ 情绪 " + sent_txt + "（" + mood + "）｜ 周期 " + _esc(str(cycle))
             + ' ｜ <span class="regime-badge ' + _regime_cls + '">' + _esc(_regime_label) + '</span>')
    h.append('<br><span style="font-size:12px;color:var(--text-secondary);">策略：' + _esc(_regime_strategy) + '</span>')
    stats = []
    if n_at_buy:
        stats.append(str(n_at_buy) + " 个已到买点")
    if n_near:
        stats.append(str(n_near) + " 个接近买点（≤5%）")
    if n_loss:
        stats.append(str(n_loss) + " 个持仓浮亏")
    if stats:
        h.append('<br><span style="color:var(--accent);font-weight:600;">' + " · ".join(stats) + "</span>")
    # 组合并发仓位提示(P2, 2026-08-04): Σ建仓/补仓建议仓位超上限时预警(展示层, 不改信号)
    demand = sum(float(r.get("position_limit") or 0) for r in results
                 if (r.get("portfolio_advice") or {}).get("action") in ("可分批建仓", "可分批补仓"))
    if demand > PORTFOLIO_CAP_CONCURRENT + 1e-9:
        h.append(('<br><span style="color:var(--yellow);font-weight:600;">并发建议仓位 {:.0f}%（上限 {:.0f}%），'
                  '超出 {:.0f}%：信号扎堆时优先处理排序靠前的建仓/补仓，避免单日同时开仓过多'
                  '（回测：超限持仓并发最高1200%、回撤可达-85%）</span>').format(
            demand * 100, PORTFOLIO_CAP_CONCURRENT * 100, (demand - PORTFOLIO_CAP_CONCURRENT) * 100))
    # B1 组合回撤熔断提示(2026-08-05): 持仓市值距峰值回撤超阈值 -> 建议暂停新开仓/补仓
    # 回测(data/b1_risk_validation.json): cap0.8+熔断10% 总收益+60.5%/maxDD-12.0%, 优于无熔断+54.6%/-15.3%
    _dd = (risk_ctx or {}).get("drawdown") or {}
    if _dd.get("breaker_active"):
        h.append(('<br><span style="color:var(--red);font-weight:600;">组合回撤熔断：持仓市值距峰值回撤 '
                  '{:.1f}%（阈值 {:.0f}%，收复峰值解除），建议暂停新开仓/补仓'
                  '（回测：熔断10%组合总收益+60.5%、最大回撤-12.0%，优于无熔断+54.6%/-15.3%）'
                  '</span>').format(
            _dd["drawdown_pct"], _dd["threshold_pct"]))
    h.append("</div></div>")
    # 持仓分析
    if held:
        h.append('<div class="card" style="margin-bottom:16px;"><div class="card-header"><span class="card-title">持仓分析 (' + str(len(held)) + ")</span></div><div class=\"table-wrap\"><table><thead><tr><th>物品</th><th>成本/现价</th><th>盈亏</th><th>评分</th><th>距买点</th><th>建议</th></tr></thead><tbody>")
        for r in held:
            pnl_pct = _pnl_pct(r)
            pa = r.get("portfolio_advice", {}) or {}
            g = (r.get("grade") or "?").lower()
            pnl_c = "green" if pnl_pct > 5 else ("red" if pnl_pct < -5 else "")
            h.append("<tr><td>" + (name_link(r["name"]) if name_link else _esc(r["name"])) + "</td>")
            h.append("<td>¥" + "%.2f" % r["avg_cost"] + " → <strong>¥" + "%.2f" % r["price_rmb"] + "</strong></td>")
            h.append('<td class="' + pnl_c + '">' + "%.1f" % pnl_pct + "%</td>")
            h.append('<td><span class="badge badge-' + g + '">' + _esc(str(r.get("grade", "?"))) + "</span></td>")
            h.append("<td>" + _bd_cell(r.get("buy_distance")) + "</td>")
            _sp_line = ""
            _sp = pa.get("stop_plan") or {}
            if _sp:
                _sp_line = ('<br><span style="font-size:10px;color:var(--text-secondary);">🛑 止损评估：'
                            + _esc(str(_sp.get("state", ""))) + " · " + _esc(str(_sp.get("action", "")))
                            + (' · 参考(现价) ¥%.2f' % float(_sp.get("exec_price") or 0) if _sp.get("sell_action") else "")
                            + (' · 卖出%s件' % int(_sp["sell_qty"]) if _sp.get("sell_action") else "")
                            + '</span>')
            h.append('<td>' + _action_badge(pa) + "<br><span style=\"font-size:11px;color:var(--text-muted);\">" + _esc(pa.get("suggest", "")) + "</span>" + _sp_line + _exec_btn(r["name"], pa, r["price_rmb"]) + "</td></tr>")
        h.append("</tbody></table></div></div>")
    # 关注列表（非持仓）
    if unheld:
        h.append('<div class="card" style="margin-bottom:16px;"><div class="card-header"><span class="card-title">关注列表 (' + str(len(unheld)) + ")</span></div><div class=\"table-wrap\"><table><thead><tr><th>物品</th><th>现价</th><th>评分</th><th>估值</th><th>距买点</th><th>建议</th></tr></thead><tbody>")
        for r in unheld:
            pa = r.get("portfolio_advice", {}) or {}
            g = (r.get("grade") or "?").lower()
            h.append("<tr><td>" + (name_link(r["name"]) if name_link else _esc(r["name"])) + "</td>")
            h.append("<td>¥" + "%.2f" % r["price_rmb"] + "</td>")
            h.append('<td><span class="badge badge-' + g + '">' + _esc(str(r.get("grade", "?"))) + "</span></td>")
            h.append('<td style="font-size:12px;">' + _esc(str(r.get("valuation_tier", "?"))) + '<br><span style="color:var(--text-muted);">pct=' + "%.1f" % r.get("percentile_90d", 50) + "%</span></td>")
            h.append("<td>" + _bd_cell(r.get("buy_distance")) + "</td>")
            h.append('<td>' + _action_badge(pa) + "<br><span style=\"font-size:11px;color:var(--text-muted);\">" + _esc(pa.get("suggest", "")) + "</span>" + _exec_btn(r["name"], pa, r["price_rmb"]) + "</td></tr>")
        h.append("</tbody></table></div></div>")
    # 失败
    if errors:
        h.append('<div class="card" style="border-color:var(--red);"><div class="card-header"><span class="card-title">扫描失败</span></div>')
        for e in errors:
            h.append('<div style="margin-bottom:4px;"><strong>' + _esc(e["name"]) + "</strong>: <span style=\"color:var(--red);\">" + _esc(e.get("error", "")) + "</span></div>")
        h.append("</div>")
    return "\n".join(h)