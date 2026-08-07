# -*- coding: utf-8 -*-
"""Buy-distance quantization: how far current price is from the buy reference.

把"当前价距买点还有多远"量化为：价格差 + 百分比 + 进度条（bar_pct）。

目标价永远向下看（target <= 当前价），参考位不会高于现价。
三态自适应（2026-08-03 重构）：

- 下跌寻底: target = 估值线（pct30 -> z-1.5 -> 90日低，逐级下探）
- 等待回踩: target = 买入区间上沿 / k*ATR 支撑
- 强势回踩: target = 最近 MA 支撑（MA7/MA30 取低）
- 已到买点:        当前价已进入买入区或低于所有参考线

兼容旧字段 drop_price / drop_to_entry_pct / line_price / drop_to_line_pct / pct_gap 之外，新增：
  current_price, target_price, gap_pct, gap_rmb, scenario, scenario_label,
  summary, bar_pct, pct30_price, z15_price, low90_price, ma7, ma30,
  z_gap, th_gap, entry_zone, ref, anchor_price, anchor_note

口径约定（2026-08-03 修复）：场景/目标价/距离全部基于 chart K线收盘价（与
percent_90d 同源），避免与悠悠锚定价混源产生自相矛盾的结论（守护者 2026-08-03：
K线收盘处于 48.8 分位，悠悠价 55 却被判「已低于 90 日低 ¥65.71」）。anchor_price
仅作展示字段，偏差 ≥15% 时输出 anchor_note 提示。
"""
import statistics

ENTRY_PCT = 30          # 下跌寻底估值线：90日 30 分位价（pct<=30 低估）
ENTRY_Z = -1.5          # 抄底 z 线（-1.5σ）
MARKET_ENTRY_Z = 0.0    # 大盘企稳 z 线（z<=0 视为企稳）
TH_REF = 55             # 趋势确认参考 TH（三区语义：恐慌<35 黄金坑 / 35-54 摩擦带 / ≥55 趋势确认；下跌寻底价格线为主）
TH_BULL = 30            # 牛/震荡市 TH 参考阈值（v5.2 放宽）
TH_PANIC = 35            # 恐慌黄金坑上限（TH<35 黄金坑 / 35-54 摩擦带 / ≥55 趋势确认）
BAR_CAP = 20.0          # 进度条满格 20%（距离再远也封顶）

# 分批建仓方案 C（2026-08-04 回测最优，88 信号基准，hold14 资金加权期望 +48.13% vs 一次性按 position_limit +31.35%）
#   首仓 10%（信号日）→ 较首仓价再跌 10% 加 20% → 跌 15% 加 30%（总仓位上限 60%）
FIRST_TRANCHE = 10                  # 首仓仓位（信号日建）
TRANCHES = ((10, 20), (15, 30))     # (相对首仓价跌幅%, 加仓仓位%)
TOTAL_CAP = FIRST_TRANCHE + sum(w for _, w in TRANCHES)   # 60%


def tranche_plan_text():
    """分批建仓方案文案（纯展示层）：首仓10% → 跌10%加20% → 跌15%加30%"""
    parts = ["首仓{}%".format(FIRST_TRANCHE)]
    parts += ["跌{}%加{}%".format(thr, w) for thr, w in TRANCHES]
    return " → ".join(parts)


def _get(obj, key, default=None):
    """Read attribute-or-key from dataclass / dict."""
    if obj is None:
        return default
    if isinstance(obj, dict):
        return obj.get(key, default)
    return getattr(obj, key, default)


def _f(v, default=0.0):
    """Safe float cast (None/NaN/str -> default)."""
    try:
        x = float(v)
    except (TypeError, ValueError):
        return default
    return x if x == x else default


def _atr_pct(prices, n=14):
    """14日 ATR 估算；与 item_analysis 内部口径一致，clamp 1%~10% 防异常"""
    returns = [(prices[i] - prices[i-1]) / prices[i-1]
               for i in range(max(1, len(prices) - n), len(prices)) if prices[i-1] > 0]
    if not returns:
        return 0.03
    return max(0.01, min(0.10, sum(abs(r) for r in returns) / len(returns)))




def _stabilizing(prices, window=90):
    """企稳判定（与超跌买入例外同口径，P0 2026-08-03）：最近 2 日未创新低 + 近 3 日转涨。

    纯展示层：仅用于距买点参考位选择（下跌中继不追跌），不触碰信号引擎。
    数据不足 5 点视为企稳（宽松处理，避免误拦）。
    """
    win = [_f(p) for p in (prices or []) if _f(p) > 0]
    if len(win) < 5:
        return True
    low = min(win[-window:])
    no_new_low2 = win[-1] > low and (len(win) < 2 or win[-2] > low)
    base = win[-4] if len(win) >= 4 else win[0]
    chg3d = (win[-1] / base - 1.0) * 100.0 if base > 0 else 0.0
    return bool(no_new_low2 and chg3d > 0)


def _window_stats(prices, n=90):
    """90d 窗口统计（估值线 + MA 支撑）

    - pct30_price: 30 分位价（与 percent_90d 口径一致）
    - mad_scale: mad*1.4826，与 item_analysis._analyze_position / index_analysis._zscore 同口径
    """
    win = [_f(p) for p in (prices or []) if _f(p) > 0]
    if len(win) < 10:
        return None
    win = win[-n:]
    cur = win[-1]
    sorted_p = sorted(win)
    idx30 = min(len(sorted_p) - 1, int(round(0.30 * len(sorted_p))))
    pct30_price = sorted_p[idx30]
    med = statistics.median(win)
    mad = statistics.median([abs(v - med) for v in win])
    return {"win": win, "cur": cur, "pct30_price": pct30_price,
            "med": med, "mad": mad, "mad_scale": mad * 1.4826,
            "low90": min(win), "ma7": statistics.mean(win[-7:]) if len(win) >= 7 else None,
            "ma30": statistics.mean(win[-30:]) if len(win) >= 30 else None}


def _gap_pct(cur, target):
    """距离百分比：target 低于 cur 才为正"""
    if cur <= 0 or target <= 0:
        return 0.0
    return round((cur - target) / cur * 100, 1)


def _finish(scenario, scenario_label, cur, target, st, th, pct, z,
            entry_zone=None, summary=None, th_target=TH_REF, anchor_price=None,
            supply_signal="none", stabilizing=False):
    """统一收尾：兜底 target<=cur、构造 summary/进度条/兼容字段。

    anchor_price: 悠悠有品锚定价，仅作展示（不参与场景/目标/距离计算），
                  与 K线口径偏差 ≥15% 时输出 anchor_note 提示。
    """
    if target is None or target >= cur:
        target = cur
        scenario = scenario if scenario == "done" else "extreme"
        scenario_label = "极端超跌" if scenario == "extreme" else scenario_label
    gap_pct = _gap_pct(cur, target)
    gap_rmb = round(cur - target, 2)
    bar = min(100.0, max(0.0, gap_pct / BAR_CAP * 100)) if gap_pct > 0 else 100.0
    if summary is None:
        summary = ("再跌 {:.1f}% 到 ¥{:.2f} 触发买点".format(gap_pct, gap_rmb)
                   if gap_pct > 0 else "已到买点区间，可分批建仓：" + tranche_plan_text())
    z15 = round(st["med"] - 1.5 * st["mad_scale"], 2) if st["mad_scale"] else None
    anchor = round(anchor_price, 2) if (anchor_price and anchor_price > 0) else None
    anchor_note = None
    if anchor and cur > 0:
        dev = (anchor - cur) / cur * 100
        if abs(dev) >= 15.0:
            anchor_note = ("悠悠锚价 ¥{:.2f} 与K线收盘 ¥{:.2f} 偏差 {:.0f}%，距买点按K线口径计算（与百分位同源），建议核实K线数据".format(
                anchor, round(cur, 2), dev))
    # stage 按价格与参考线比较（与 summary 分支严格一致），pct/z 仅作展示
    if scenario == "done":
        stage = 0
    elif scenario == "extreme":
        stage = 4
    elif scenario == "bottom":
        if cur > st["pct30_price"]:
            stage = 1
        elif z15 and cur > z15:
            stage = 2
        else:
            stage = 3
    elif scenario == "accumulate":
        stage = 2
    else:
        stage = None
    pct_ok = bool(cur <= st["pct30_price"])
    z_ok = bool(z15 and cur <= z15)
    th_ok = bool(th >= th_target)
    th_zone = "panic" if th < TH_PANIC else ("friction" if th < TH_REF else "confirm")
    return {
        "kind": "item",
        "scenario": scenario,
        "scenario_label": scenario_label,
        "stage": stage,
        "stabilizing": stabilizing,
        "th_zone": th_zone,
        "supply_signal": supply_signal,
        "pct_ok": pct_ok,
        "z_ok": z_ok,
        "th_ok": th_ok,
        "ref": "供给吸筹=MA支撑回踩｜下跌寻底=低估线→超跌线→90日最低(企稳才下探)｜等待回踩=买入区上沿｜强势回踩=MA支撑",
        "current_price": round(cur, 2),
        "anchor_price": anchor,
        "anchor_note": anchor_note,
        "target_price": round(target, 2),
        "gap_pct": gap_pct,
        "gap_rmb": gap_rmb,
        "in_entry_zone": bool(entry_zone and entry_zone.get("low", 0) <= cur <= entry_zone.get("high", 0)),
        "entry_zone": entry_zone,
        # 兼容旧字段
        "drop_price": round(target, 2),
        "drop_to_entry_pct": gap_pct,
        "pct30_price": round(st["pct30_price"], 2),
        "z15_price": z15,
        "low90_price": round(st["low90"], 2),
        "ma7": round(st["ma7"], 2) if st["ma7"] else None,
        "ma30": round(st["ma30"], 2) if st["ma30"] else None,
        "pct_gap": round(max(0.0, pct - ENTRY_PCT), 1),
        "z_gap": round(max(0.0, z - ENTRY_Z), 2) if z > ENTRY_Z else 0.0,
        "th_gap": round(max(0.0, th_target - th), 0),
        "th_score": th,
        "tranche_plan": tranche_plan_text(),
        "summary": summary,
        "bar_pct": round(bar, 0),
    }


def compute_buy_distance(prices, position, th_score, price_zones=None, cycle_phase="unknown", action=None, anchor_price=None, supply=None):
    """单品距买点（v3 去量理念，2026-08-07）：企稳/吸筹驱动，不追跌。

    场景优先级：
    - done: 已到买点（buy 信号/入场区内）
    - accumulate: 供给吸筹（供给收缩+价稳/涨），买点=近场 MA 支撑
    - breakout: 强势回踩（TH>=60 / markup），买点=MA 支撑
    - pullback: 等待回踩（买入区上沿）
    - bottom: 下跌寻底（企稳才允许下探 pct30→z-1.5→90日低；未企稳=下跌中继，等企稳不追跌）
    - extreme: 已破 90 日最低，等待企稳信号

    anchor_price: 悠悠有品锚定价，仅作展示当前价（不参与场景/目标/距离计算）；
    场景/目标/距离全部基于 chart K线收盘价（与 percent_90d 同源），
    避免混源得出「已低于90日低」等矛盾结论（展示层，不改信号）。
    """
    st = _window_stats(prices)
    if st is None:
        return None
    cur = st["cur"]
    pct30_price = st["pct30_price"]
    z15_price = round(st["med"] - 1.5 * st["mad_scale"], 2) if st["mad_scale"] else None
    low90 = st["low90"]
    atr_pct = _atr_pct(prices)
    stabilizing = _stabilizing(prices)

    pct = _f(_get(position, "percentile_90d", None), 50.0)
    z = _f(_get(position, "zscore_90d", None), 0.0)
    th = _f(th_score, 50.0)

    # 供给信号（v2 去量：在售量为唯一量源，吸筹=供给收缩+价稳/涨）
    supply_signal = "none"
    if isinstance(supply, dict):
        _risk = supply.get("supply_risk")
        _trend = supply.get("supply_trend")
        if _risk == "hoarding" or _trend == "contracting":
            supply_signal = "hoarding"
        elif _risk == "dumping":
            supply_signal = "dumping"

    entry = _get(price_zones, "entry", None) or {}
    e_lo = _f(entry.get("low", 0) or 0)
    e_hi = _f(entry.get("high", 0) or 0)
    entry_zone = {"low": round(e_lo, 2), "high": round(e_hi, 2)} if (e_lo > 0 and e_hi >= e_lo) else None

    def _ma_support():
        supps = [x for x in (st["ma7"], st["ma30"]) if x]
        s = min(supps) if supps else round(cur * (1 - atr_pct), 2)
        return s if s < cur else round(cur * (1 - atr_pct), 2)

    # ---- 已到买点 ----
    if action == "buy" or (entry_zone and entry_zone["low"] <= cur <= entry_zone["high"]):
        return _finish("done", "已到买点", cur, cur, st, th, pct, z, entry_zone,
                       summary="当前已在买点区间（或已触发买入信号），按计划分批建仓：" + tranche_plan_text(),
                       anchor_price=anchor_price, supply_signal=supply_signal, stabilizing=stabilizing)

    # ---- 供给吸筹（v2 理念）：吸筹期买点就近 = MA 支撑，不追跌 ----
    if supply_signal == "hoarding":
        support = _ma_support()
        summary = "供给收缩·吸筹中，回踩 参考支撑 ¥{:.2f}（-{:.1f}%）即可分批建仓".format(support, _gap_pct(cur, support))
        return _finish("accumulate", "供给吸筹·回踩即买", cur, support, st, th, pct, z, entry_zone,
                       summary=summary, anchor_price=anchor_price, supply_signal=supply_signal, stabilizing=stabilizing)

    if th >= 60 or cycle_phase == "markup":
        # 突破/趋势健康：回踩 = 最近 MA（MA7/MA30 取低），无 MA 用 ATR 支撑
        target = _ma_support()
        summary = "回踩/突破 参考支撑 ¥{:.2f}（-{:.1f}%）".format(target, _gap_pct(cur, target))
        return _finish("breakout", "强势回踩", cur, target, st, th, pct, z, entry_zone,
                       summary=summary, anchor_price=anchor_price, supply_signal=supply_signal, stabilizing=stabilizing)

    if e_hi > 0 and e_hi < cur:
        # 等待回踩 = 买入区间上沿支撑
        target = e_hi
        summary = "回踩 参考买入区上沿 ¥{:.2f}（-{:.1f}%）".format(target, _gap_pct(cur, target))
        return _finish("pullback", "等待回踩", cur, target, st, th, pct, z, entry_zone,
                       summary=summary, anchor_price=anchor_price, supply_signal=supply_signal, stabilizing=stabilizing)

    # ---- 下跌寻底：企稳才允许下探（超跌买入例外同口径：3日转涨+未创新低），否则等企稳不追跌 ----
    _tag = "下跌寻底" if stabilizing else "下跌中继·等企稳"
    if cur > pct30_price:
        if stabilizing:
            target = pct30_price
            summary = "现价 ¥{:.2f}，距低估参考价 ¥{:.2f} 还差 {:.1f}%（约 ¥{:.2f}）".format(
                cur, target, _gap_pct(cur, target), cur - target)
        else:
            target = _ma_support()
            summary = "下跌中继·未企稳（3日未转涨/仍在创新低），不追跌——等企稳信号后再介入，回踩参考 ¥{:.2f}（-{:.1f}%）".format(
                target, _gap_pct(cur, target))
        return _finish("bottom", _tag, cur, target, st, th, pct, z, entry_zone,
                       summary=summary, anchor_price=anchor_price, supply_signal=supply_signal, stabilizing=stabilizing)
    if z15_price and cur > z15_price:
        if stabilizing:
            target = z15_price
            summary = "已进入低估区（现价低于 ¥{:.2f}）；距超跌参考价 ¥{:.2f} 还差 {:.1f}%（约 ¥{:.2f}）".format(
                pct30_price, target, _gap_pct(cur, target), cur - target)
        else:
            target = _ma_support()
            summary = "已进入低估区（低于 ¥{:.2f}）但下跌中继·未企稳，不追跌——等企稳（3日转涨+未创新低）再介入，回踩参考 ¥{:.2f}（-{:.1f}%）".format(
                pct30_price, target, _gap_pct(cur, target))
        return _finish("bottom", _tag, cur, target, st, th, pct, z, entry_zone,
                       summary=summary, anchor_price=anchor_price, supply_signal=supply_signal, stabilizing=stabilizing)
    if low90 < cur:
        if stabilizing:
            target = low90
            summary = "已进入超跌区（现价低于 ¥{:.2f}）；再跌 {:.1f}% 到 90 日最低 ¥{:.2f}".format(
                z15_price or 0, _gap_pct(cur, target), target)
        else:
            target = _ma_support()
            summary = "已进入超跌区（低于 ¥{:.2f}）但未企稳，不追跌——等企稳信号（3日转涨+未创新低）再介入，回踩参考 ¥{:.2f}（-{:.1f}%）".format(
                z15_price or 0, target, _gap_pct(cur, target))
        return _finish("bottom", _tag, cur, target, st, th, pct, z, entry_zone,
                       summary=summary, anchor_price=anchor_price, supply_signal=supply_signal, stabilizing=stabilizing)
    return _finish("extreme", "极端超跌", cur, cur, st, th, pct, z, entry_zone,
                   summary="已跌破 90 日最低价 ¥{:.2f}，极端超跌，等待企稳信号".format(low90),
                   supply_signal=supply_signal, stabilizing=stabilizing)



def compute_market_buy_distance(values, pct, z, th_score, regime="unknown", action="watch", action_label=""):
    """大盘距买点（v3 去量理念，2026-08-07）：TH 三区化 + 企稳闸门，不追跌。

    - buy 信号已触发→ done
    - 牛/震荡或 TH>=50 → 强势回踩（MA 支撑）
    - TH<35 恐慌黄金坑 → 买点=企稳参考位（z0/MA），等企稳（不再一路下探到 90 日低）
    - 35<=TH<50 摩擦带/熊市 → 深值寻底（企稳才允许下探 pct30→z0→90日低；未企稳=等企稳不追跌）
    """
    st = _window_stats(values)
    if st is None:
        return None
    cur = st["cur"]
    pct30_price = st["pct30_price"]
    z15_price = round(st["med"] - 1.5 * st["mad_scale"], 2) if st["mad_scale"] else None
    z0_price = round(st["med"], 2)
    low90 = st["low90"]
    atr_pct = _atr_pct(values)
    stabilizing = _stabilizing(values)
    th = _f(th_score, 50.0)
    pct = _f(pct, 50.0)
    z = _f(z, 0.0)
    th_zone = "panic" if th < TH_PANIC else ("friction" if th < TH_REF else "confirm")

    th_target = TH_BULL if regime in ("bull", "sideways") else TH_REF
    th_gap = max(0.0, th_target - th)
    pct_gap = max(0.0, pct - ENTRY_PCT)
    z_gap = max(0.0, z - MARKET_ENTRY_Z) if z > MARKET_ENTRY_Z else 0.0

    def _ma_support():
        supps = [x for x in (st["ma7"], st["ma30"]) if x]
        s = min(supps) if supps else round(cur * (1 - atr_pct), 2)
        return s if s < cur else round(cur * (1 - atr_pct), 2)

    def _stabilize_target():
        t = min(z0_price, _ma_support()) if z0_price else _ma_support()
        return t if t < cur else round(cur * (1 - atr_pct), 2)

    if action == "buy":
        target, scenario, sl = cur, "done", "已到买点"
        summary = "已到买点（{}），按计划分批建仓：{}".format(action_label or "大盘 buy", tranche_plan_text())
    elif regime in ("bull", "sideways") or th >= 50:
        # 突破/回踩：最近 MA 支撑（MA7/MA30 取低），无 MA 用 ATR 支撑
        target = _ma_support()
        scenario, sl = "breakout", "强势回踩"
        summary = "回踩 参考支撑 {:.0f}（-{:.1f}%）".format(target, _gap_pct(cur, target))
    elif th < TH_PANIC:
        # 恐慌黄金坑（TH<35）：机会区已到，参考位提升为企稳参考位，不再一路下探到 90 日低
        target = _stabilize_target()
        scenario, sl = "panic", "恐慌黄金坑·等企稳"
        summary = "恐慌区(TH<35)黄金坑，指数 {:.0f} 距企稳参考位 {:.0f} 还差 {:.1f}%（约 {:.0f} 点）——等企稳（3日转涨+未创新低）再分批建仓".format(
            cur, target, _gap_pct(cur, target), cur - target)
    elif cur > pct30_price:
        if stabilizing:
            target = pct30_price
            summary = "现指数 {:.0f}，距低估参考位 {:.0f} 还差 {:.1f}%（约 {:.0f} 点）".format(
                cur, target, _gap_pct(cur, target), cur - target)
        else:
            target = _stabilize_target()
            summary = "摩擦带·下跌中继未企稳，不追跌——等企稳（3日转涨+未创新低）再介入，参考位 {:.0f}（-{:.1f}%）".format(
                target, _gap_pct(cur, target))
        scenario, sl = "bottom", "深值寻底·等企稳" if not stabilizing else "深值寻底"
    elif z0_price and cur > z0_price:
        if stabilizing:
            target = z0_price
            summary = "已进入低估区（{:.0f} 以下）；距企稳参考位 {:.0f} 还差 {:.1f}%（约 {:.0f} 点）".format(
                pct30_price, target, _gap_pct(cur, target), cur - target)
        else:
            target = _stabilize_target()
            summary = "已进入低估区（低于 {:.0f}）但未企稳，不追跌——等企稳信号再介入，参考位 {:.0f}（-{:.1f}%）".format(
                pct30_price, target, _gap_pct(cur, target))
        scenario, sl = "bottom", "深值寻底·等企稳" if not stabilizing else "深值寻底"
    elif low90 < cur:
        if stabilizing:
            target = low90
            summary = "已进入企稳区（低于 {:.0f}）；再跌 {:.1f}% 到 90 日最低 {:.0f}".format(
                z15_price or 0, _gap_pct(cur, target), target)
        else:
            target = _stabilize_target()
            summary = "已进入超跌区（低于 {:.0f}）但未企稳，不追跌——等企稳信号再介入，参考位 {:.0f}（-{:.1f}%）".format(
                z15_price or 0, target, _gap_pct(cur, target))
        scenario, sl = "bottom", "深值寻底·等企稳" if not stabilizing else "深值寻底"
    else:
        target, scenario, sl = cur, "extreme", "极端超跌"
        summary = "已跌破 90 日最低 {:.0f}，极端超跌，等待企稳信号".format(low90)

    gap_pct = _gap_pct(cur, target)
    gap_rmb = round(cur - target, 2)
    bar = min(100.0, max(0.0, gap_pct / BAR_CAP * 100)) if gap_pct > 0 else 100.0

    # stage 按指数与参考线比较（与 summary 分支严格一致）
    if scenario == "done":
        stage = 0
    elif scenario == "extreme":
        stage = 4
    elif scenario == "panic":
        stage = 2
    elif scenario == "bottom":
        if cur > pct30_price:
            stage = 1
        elif z15_price and cur > z15_price:
            stage = 2
        else:
            stage = 3
    else:
        stage = None
    return {
        "kind": "market",
        "scenario": scenario,
        "scenario_label": sl,
        "stage": stage,
        "stabilizing": stabilizing,
        "th_zone": th_zone,
        "supply_signal": "none",
        "pct_ok": bool(cur <= pct30_price),
        "z_ok": bool(z15_price and cur <= z15_price),
        "th_ok": bool(th >= th_target),
        "ref": "恐慌黄金坑=企稳参考位｜深值寻底=低估线→企稳线→90日最低(企稳才下探)｜强势回踩=MA支撑",
        "current_price": round(cur, 2),
        "target_price": round(target, 2),
        "gap_pct": gap_pct,
        "gap_rmb": gap_rmb,
        # 兼容旧字段
        "line_price": round(target, 2),
        "drop_to_line_pct": gap_pct,
        "pct30_price": round(pct30_price, 2),
        "z0_price": z0_price,
        "z15_price": z15_price,
        "low90_price": round(low90, 2),
        "ma7": round(st["ma7"], 2) if st["ma7"] else None,
        "ma30": round(st["ma30"], 2) if st["ma30"] else None,
        "pct_gap": round(pct_gap, 1),
        "z_gap": round(z_gap, 2),
        "th_gap": round(th_gap, 0),
        "th_score": th,
        "tranche_plan": tranche_plan_text(),
        "th_target": th_target,
        "regime": regime,
        "action": action,
        "action_label": action_label or "",
        "summary": summary,
        "bar_pct": round(bar, 0),
    }
