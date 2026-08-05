"""Batch scan, discover high-score items, and portfolio advice."""
import asyncio, json, logging, traceback
from datetime import datetime

from . import collector_csqaq, collector, db, item_analysis, index_analysis
from .buy_distance import tranche_plan_text
from .config import TOPUP_EXPECTANCY_STATS, PORTFOLIO_CAP_CONCURRENT

_log = logging.getLogger("batch_scan")

_EMOJI_PREFIXES = ("🟢 ", "🟡 ", "🟠 ", "🔴 ", "🟤 ", "💥 ")


def signal_guidance(action_label: str = "", expectancy: dict = None) -> dict:
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
        hold = "恐慌共振类：14d胜率95%，30d胜率83%，可持有30日"
    elif "超跌" in label:
        sig_type, type_label = "oversold", "超跌反弹"
        hold = "超跌反弹类：默认14日退出（30d期望回落）"
    elif "吸筹" in label:
        sig_type, type_label = "accumulate", "周期吸筹"
        hold = "周期吸筹类：默认14日退出（非恐慌段30d期望≈0）"
    else:
        sig_type, type_label = "base", "低位低估"
        hold = "默认14日退出（非恐慌段30d期望≈0，最长14d持仓）"
    if expectancy and isinstance(expectancy, dict) and expectancy.get("label"):
        type_label = expectancy["label"]
    return {"signal_type": sig_type, "type_label": type_label, "hold_guidance": hold}


def _portfolio_advice(holding, avg_cost, qty, current_price, analysis, market_th=None, sentiment_score=50.0):
    """Generate personalized portfolio advice based on cost basis and current position.
    sentiment_score: contrarian 0-100 (0=extreme greed, 100=extreme fear), default neutral.
    补仓分层阈值来自全量日记录回放(2026-08-04, 2025-11-02~2026-07-13, warmup=60, 只读引擎):
      可分批补仓(条件+融合buy): 14d胜率54%/均值+5.4% | 半山腰(25~40): 14d均值≈0 |
      sent<=30(贪婪): 14d均值-2.4% | 大盘未配合(mth<45): 14d均值-1.0%
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
            "watch": "观望等待机会",
            "hold": "持有观察",
            "reduce": "暂不建议入场",
            "sell": "暂不建议入场",
            "avoid": "暂不建议入场",
        }
        action = action_map.get(fusion_action, "观望等待机会")
        risk = "low" if fusion_action == "buy" else ("high" if fusion_action in ("sell", "avoid", "reduce") else "medium")
        detail = fusion.get("action_detail") or ""
        reason = label or "以报告决策为准"
        if label and detail and detail not in label:
            reason = f"{label}：{detail}"
        # 非持仓: 距建仓参考线的距离(2026-08-03), 便于看离买点还有多远
        _pct = getattr(analysis.position, "percentile_90d", 50)
        _z = getattr(analysis.position, "zscore_90d", 0)
        _th_obj = analysis.trend_health or {}
        _th = _th_obj.get("score", 50) if isinstance(_th_obj, dict) else getattr(_th_obj, "score", 50)
        _gd = signal_guidance(fusion.get("action_label", ""), (getattr(analysis, "price_zones", None) or {}).get("expectancy"))
        if fusion_action == "buy":
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
                if _th < 55:
                    _gaps.append(f"单品TH={_th:.0f}距55还差{55 - _th:.0f}分")
                if _gaps:
                    _suggest = "；".join(_gaps) + "（参考线：pct≤30% + TH≥55 + z≤-1.5，恐慌共振场景TH可更低）"
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
    cycle_phase = getattr(analysis.cycle, "phase", "unknown")

    advice = {"cost_price": avg_cost, "current_price": current_price, "qty": qty,
              "pnl_pct": round(pnl_pct, 1), "cost_total": round(cost_total, 2), "market_value": round(market_value, 2)}
    _fusion = getattr(analysis, "fusion_decision", {}) or {}
    _fusion_act = _fusion.get("action", "") if isinstance(_fusion, dict) else ""

    if pnl_pct > 20 and th_score < 40:
        advice["action"] = "建议止盈减仓"
        advice["reason"] = f"盈利{pnl_pct:.0f}%且趋势转弱"
        advice["suggest"] = f"可卖出{max(1, qty//2)}件锁定利润"
    elif pnl_pct > 50:
        advice["action"] = "大幅盈利，部分止盈"
        advice["reason"] = f"盈利{pnl_pct:.0f}%，建议卖出1/3~1/2"
        advice["suggest"] = f"可卖出{max(1, qty//3)}~{max(1, qty//2)}件"
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
        # 市场极度贪婪：禁止补仓（回测 sent<=30: 30d胜率0%, 均-14%）
        if sent <= 30:
            advice["action"] = "禁止补仓"
            advice["reason"] = f"浮亏{pnl_pct:.0f}%但市场贪婪(sent={sent:.0f})，逆势抄底期望为负"
            advice["suggest"] = (f"情绪贪婪(sent={sent:.0f}，≤30禁补)，距可补区间还差{max(0, 30 - sent):.0f}分，"
                                 f"等情绪转中性/恐惧再考虑（回测：贪婪期补仓14d均值{TOPUP_EXPECTANCY_STATS['greedy']['avg14']:+.1f}%）")
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
            # A方向(2026-08-03): 引用price_zones买入区间给出补仓价位+摊薄成本（与报告同源）
            _pz = getattr(analysis, "price_zones", None) or {}
            _entry = _pz.get("entry") or {}
            _cur = _pz.get("current") or current_price
            _e_lo = _entry.get("low", 0) or 0
            _e_hi = _entry.get("high", 0) or 0
            _q = max(1, qty // 3)
            if _e_lo > 0 and _e_hi > 0 and _e_hi < _cur:
                _mid = round((_e_lo + _e_hi) / 2, 2)
                _steps = [(_e_hi, _q), (_mid, _q), (_e_lo, _q)]
                _drops = [round((p - _cur) / _cur * 100, 1) for p, _ in _steps]
                _cost_after = round((avg_cost * qty + sum(p * n for p, n in _steps)) / (qty + sum(n for _, n in _steps)), 2)
                advice["add_positions"] = [{"price": p, "qty": n, "drop_pct": d} for (p, n), d in zip(_steps, _drops)]
                advice["entry_zone"] = {"low": _e_lo, "high": _e_hi}
                advice["avg_cost_after"] = _cost_after
                advice["suggest"] = (f"可分3批补仓，每批约{_q}件：批1 ¥{_e_hi:.2f}({_drops[0]:.1f}%)、"
                                     f"批2 ¥{_mid:.2f}({_drops[1]:.1f}%)、批3 ¥{_e_lo:.2f}({_drops[2]:.1f}%)；"
                                     f"补满后摊薄成本约¥{_cost_after:.2f}；单批不超过仓位上限15%"
                                     f"（回测：补仓点14d胜率{TOPUP_EXPECTANCY_STATS['topup_ok']['win14']:.0f}%、"
                                     f"均值+{TOPUP_EXPECTANCY_STATS['topup_ok']['avg14']:.1f}%）")
            else:
                advice["suggest"] = (f"可分2~3批加仓{_q}件，单批不超过仓位上限15%"
                                     f"（回测：补仓点14d胜率{TOPUP_EXPECTANCY_STATS['topup_ok']['win14']:.0f}%、"
                                     f"均值+{TOPUP_EXPECTANCY_STATS['topup_ok']['avg14']:.1f}%）"
                                     f"（当前周期结构未放行买入区间，待企稳后更新补仓价位）")
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
        advice["reason"] = f"建议结合大盘走势决策"
    _gd = signal_guidance(_fusion.get("action_label", "") if isinstance(_fusion, dict) else "",
                          (getattr(analysis, "price_zones", None) or {}).get("expectancy"))
    advice["signal_type"] = _gd["signal_type"]
    advice["type_label"] = _gd["type_label"]
    advice["hold_guidance"] = _gd["hold_guidance"]
    advice["buy_distance"] = summarize_buy_distance(getattr(analysis, "buy_distance", None) or {})
    return advice

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


def sort_results(results):
    """批量扫描结果排序：按「买点接近度」排序（条件达标越多、剩余距离越近在前）。

    持仓与非持仓各自区块内排序，两区块口径一致；同接近度时持仓按浮亏升序（亏损多优先）。
    展示层排序，不影响任何引擎信号。
    """
    held, unheld = [], []
    for r in results:
        (held if r.get("holding") else unheld).append(r)
    held.sort(key=lambda r: (_proximity_key(r), _pnl_pct(r)))
    unheld.sort(key=_proximity_key)
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
        if action == "可分批补仓":
            sig_action = "可分批补仓"
        elif action == "趋势走弱，考虑止损":
            sig_action = "建议止损"
        elif gap is not None and gap <= 0:
            sig_action = "已到买点"
        else:
            continue
        signals.append({
            "name": r.get("name", ""),
            "action": sig_action,
            "holding": 1 if r.get("holding") else 0,
            "gap_pct": round(gap, 1) if gap is not None else None,
            "suggest": (pa.get("suggest") or "")[:120],
        })
    _prio = {"可分批补仓": 0, "建议止损": 1, "已到买点": 2}
    signals.sort(key=lambda s: (_prio.get(s["action"], 9),
                                s["gap_pct"] if s["gap_pct"] is not None else 999))
    return signals


def _esc(s):
    """HTML 转义（展示层防注入）。"""
    return (str(s or "").replace("&", "&amp;").replace("<", "&lt;")
            .replace(">", "&gt;").replace('"', "&quot;"))

# ---- 按建议执行 (P0-2, 2026-08-04): 展示层记账入口, 不改任何信号 ----
_EXEC_ACTION_MAP = {
    "可分批建仓": "buy",
    "可分批补仓": "add",
    "建议止盈减仓": "reduce",
    "大幅盈利，部分止盈": "reduce",
    "趋势走弱，考虑止损": "sell",
}


def _exec_btn(name, pa, price):
    """建议动作 -> 执行按钮（build 卡片里的小按钮，带 data-* 供前端弹窗）。"""
    act = (pa or {}).get("action") or ""
    ea = _EXEC_ACTION_MAP.get(act)
    if not ea:
        return ""
    return ('<button type="button" class="btn btn-accent btn-sm exec-btn" '
            'data-name="{n}" data-action="{a}" data-signal="{s}" data-price="{p:.2f}" '
            'onclick="openExecModal(this)">💼 按建议执行</button>').format(
        n=_esc(name), a=ea, s=_esc(act), p=float(price or 0))


def _bd_cell(bd):
    """距买点表格单元格：目标价 + 下杀幅度 + 微型进度条 + 条件达标徽标 + 场景标签。"""
    if not bd:
        return '<span style="font-size:11px;color:var(--text-muted);">—</span>'
    gap = bd.get("gap_pct")
    bar = min(100.0, max(0.0, float(bd.get("bar_pct") or 0)))
    at = gap is not None and gap <= 0
    color = "#4ade80" if at else "#fbbf24"
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
                conds.append('<span style="padding:1px 5px;border-radius:3px;background:rgba(34,197,94,0.15);color:#4ade80;font-size:10px;">'
                             + label + " ✓</span>")
            else:
                conds.append('<span style="padding:1px 5px;border-radius:3px;background:rgba(245,158,11,0.15);color:#fbbf24;font-size:10px;">'
                             + label + " 差" + fmt.format(v) + "</span>")
    cond_row = ('<div style="margin-top:3px;display:flex;gap:3px;flex-wrap:wrap;">'
                + "".join(conds) + "</div>") if conds else ""
    return ('<span style="font-size:11px;color:var(--text-muted);">'
            + bd.get("scenario_label", "") + "</span><br>"
            + '<b style="color:{c};">¥{t:.2f}</b>'.format(c=color, t=bd.get("target_price") or 0)
            + ' <span style="color:{c};font-size:11px;">（{g}）</span>'.format(c=color, g=gap_txt)
            + '<div style="height:5px;background:rgba(255,255,255,0.06);border-radius:3px;margin-top:3px;overflow:hidden;">'
            + '<div style="height:100%;width:{b:.0f}%;background:linear-gradient(90deg,#3b82f6,#22c55e);"></div></div>'.format(b=bar)
            + cond_row)


def build_scan_html(results, total, market_ctx=None, now_str="", name_link=None):
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
    h.append('<div class="card" style="margin-bottom:16px;"><div class="card-header"><span class="card-title">市场环境</span></div>'
             '<div style="padding:10px 14px;font-size:13px;color:var(--text-secondary);">'
             + ("指数 " + _esc("{:.0f}".format(idxv)) + " ｜" if idxv else "") + " 大盘TH=" + th_txt + " ｜ 情绪 " + sent_txt + "（" + mood + "）｜ 周期 " + _esc(str(cycle)))
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
            h.append('<td><span style="font-size:12px;font-weight:600;color:var(--accent);">' + _esc(pa.get("action", "")) + "</span><br><span style=\"font-size:11px;color:var(--text-muted);\">" + _esc(pa.get("suggest", "")) + "</span><br><span style=\"font-size:11px;color:var(--accent);\">" + _esc(pa.get("hold_guidance", "") or "") + "</span>" + _exec_btn(r["name"], pa, r["price_rmb"]) + "</td></tr>")
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
            h.append('<td><span style="font-size:12px;font-weight:600;color:var(--accent);">' + _esc(pa.get("action", "")) + "</span><br><span style=\"font-size:11px;color:var(--text-muted);\">" + _esc(pa.get("suggest", "")) + "</span>" + _exec_btn(r["name"], pa, r["price_rmb"]) + "</td></tr>")
        h.append("</tbody></table></div></div>")
    # 失败
    if errors:
        h.append('<div class="card" style="border-color:var(--red);"><div class="card-header"><span class="card-title">扫描失败</span></div>')
        for e in errors:
            h.append('<div style="margin-bottom:4px;"><strong>' + _esc(e["name"]) + "</strong>: <span style=\"color:var(--red);\">" + _esc(e.get("error", "")) + "</span></div>")
        h.append("</div>")
    return "\n".join(h)