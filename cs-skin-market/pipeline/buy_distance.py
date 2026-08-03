# -*- coding: utf-8 -*-
"""Buy-distance quantization: how far current price is from the buy reference line.

展示层辅助（不改变任何引擎决策）。回答用户的问题：「还下杀多少（% 与价格）才到买点」。

单品参考线（与 batch_scan 展示口径一致）：
  pct<=30%（90日分位） + TH>=55 + z<=-1.5（MAD 口径）
  恐慌共振场景 TH 可更低；实际买点以融合决策为准，这里只做「距离可视化」。
  首选目标 = 报告 price_zones.entry 买入区间（回调触发），无区间时退回 pct30 估值线。

大盘参考线：
  pct<=30% + TH>=55 + z<=0；牛/震荡深调场景 TH 门槛 30（v5.2 牛熊动态阈值）。
  价格参考位取 min(pct30_price, z0_price)：两个估值条件同时满足所需的价位。
"""
import statistics

ENTRY_PCT = 30          # 单品/大盘通用低估参考线（90日分位 <= 30）
ENTRY_Z = -1.5          # 单品 z 参考线
MARKET_ENTRY_Z = 0.0    # 大盘 z 参考线（融合决策 z<=0）
TH_REF = 55             # 趋势健康度参考线
TH_BULL = 30            # 牛市/震荡深调场景 TH 门槛（v5.2）
BAR_CAP = 20.0          # 距买点下杀 20% 即占满进度条


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


def _window_stats(prices, n=90):
    """90d 窗口统计，与报告口径一致。

    - pct30_price: 第 30 百分位价格（与 percent_90d 同口径近似）
    - mad_scale: mad*1.4826（与 item_analysis._analyze_position / index_analysis._zscore 一致）
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
            "med": med, "mad": mad, "mad_scale": mad * 1.4826}


def _gap_pct(cur, target):
    """还差百分之多少才到 target 价位（cur > target 时为正值）。"""
    if cur <= 0 or target <= 0:
        return 0.0
    return round((cur - target) / cur * 100, 1)


def compute_buy_distance(prices, position, th_score, price_zones=None, cycle_phase="unknown"):
    """单品：距买点参考线的距离（价格量化 + 进度条）。"""
    st = _window_stats(prices)
    if st is None:
        return None
    cur = st["cur"]
    pct30_price = st["pct30_price"]
    z15_price = round(st["med"] - 1.5 * st["mad_scale"], 2) if st["mad_scale"] else None

    pct = _f(_get(position, "percentile_90d", None), 50.0)
    z = _f(_get(position, "zscore_90d", None), 0.0)
    th = _f(th_score, 50.0)

    entry = _get(price_zones, "entry", None) or {}
    e_lo = _f(entry.get("low", 0) or 0)
    e_hi = _f(entry.get("high", 0) or 0)

    if e_lo > 0 and e_hi >= e_lo:
        in_zone = e_lo <= cur <= e_hi
        drop_to_entry = _gap_pct(cur, e_hi) if cur > e_hi else 0.0
        drop_price = e_hi
        zone = {"low": round(e_lo, 2), "high": round(e_hi, 2)}
        zone_kind = "engine_buy_zone"
    else:
        in_zone = cur <= pct30_price
        drop_to_entry = _gap_pct(cur, pct30_price)
        drop_price = pct30_price
        zone = None
        zone_kind = "valuation_line"

    th_gap = max(0.0, TH_REF - th)
    pct_gap = max(0.0, pct - ENTRY_PCT)
    z_gap = max(0.0, z - ENTRY_Z) if z > ENTRY_Z else 0.0

    if in_zone:
        if zone:
            summary = "已在买入区，可分批建仓"
        else:
            summary = "已到估值参考线附近，等融合决策确认"
            if th_gap > 0:
                summary += "（TH 还差 {:.0f} 分）".format(th_gap)
        bar = 100.0
    elif drop_to_entry > 0:
        if zone_kind == "engine_buy_zone":
            summary = "再下杀 {:.1f}%（到 ¥{:.2f}）进入买入区".format(drop_to_entry, drop_price)
        else:
            summary = "再下杀 {:.1f}%（到 ¥{:.2f}）触及低估参考线".format(drop_to_entry, drop_price)
        bar = min(100.0, max(0.0, drop_to_entry / BAR_CAP * 100))
    elif zone and cur < e_lo:
        summary = "已跌破买入区下沿（¥{:.2f}），估值更低，可关注分批机会".format(e_lo)
        bar = 100.0
    else:
        summary = "已到买点参考线附近，等融合决策确认"
        if th_gap > 0:
            summary += "（TH 还差 {:.0f} 分）".format(th_gap)
        bar = 100.0

    return {
        "kind": "item",
        "ref": "参考线：pct\u226430% + TH\u226555 + z\u2264-1.5\uff08\u6050\u614c\u5171\u632f\u573a\u666f TH \u53ef\u66f4\u4f4e\uff09",
        "current_price": round(cur, 2),
        "in_entry_zone": bool(in_zone),
        "entry_zone": zone,
        "drop_to_entry_pct": round(drop_to_entry, 1),
        "drop_price": round(drop_price, 2),
        "pct30_price": round(pct30_price, 2),
        "z15_price": z15_price,
        "pct_gap": round(pct_gap, 1),
        "z_gap": round(z_gap, 2),
        "th_gap": round(th_gap, 0),
        "th_score": th,
        "summary": summary,
        "bar_pct": round(bar, 0),
    }


def compute_market_buy_distance(values, pct, z, th_score, regime="unknown", action="watch", action_label=""):
    """大盘：距 buy 信号参考线的距离（价格量化 + 进度条）。"""
    st = _window_stats(values)
    if st is None:
        return None
    cur = st["cur"]
    pct30_price = st["pct30_price"]
    z0_price = round(st["med"], 2)          # z=0 <-> 中位数（MAD 口径）
    th = _f(th_score, 50.0)
    pct = _f(pct, 50.0)
    z = _f(z, 0.0)

    th_target = TH_BULL if regime in ("bull", "sideways") else TH_REF
    line_price = min(pct30_price, z0_price)
    drop_to_line = _gap_pct(cur, line_price)

    th_gap = max(0.0, th_target - th)
    pct_gap = max(0.0, pct - ENTRY_PCT)
    z_gap = max(0.0, z - MARKET_ENTRY_Z) if z > MARKET_ENTRY_Z else 0.0

    if action == "buy":
        summary = "已到买点：{}，可分批建仓".format(action_label or "融合决策 buy")
        bar = 100.0
    elif drop_to_line > 0:
        summary = "再下杀 {:.1f}%（指数到 ¥{:.2f}）触及低估参考线（pct\u226430/z\u22640）".format(drop_to_line, line_price)
        if th_gap > 0:
            summary += "\uff1bTH \u8fd8\u5dee {:.0f} \u5206".format(th_gap)
        bar = min(100.0, max(0.0, drop_to_line / BAR_CAP * 100))
    else:
        summary = "\u4f30\u503c\u5df2\u5230\u53c2\u8003\u7ebf\uff08pct\u226430/z\u22640\uff09\uff0c\u7b49 TH \u786e\u8ba4\uff08\u8fd8\u5dee {:.0f} \u5206\uff09".format(th_gap)
        bar = 100.0

    return {
        "kind": "market",
        "ref": "\u53c2\u8003\u7ebf\uff1apct\u226430% + TH\u226555 + z\u22640\uff08\u725b/\u9707\u8361\u6df1\u8c03\u573a\u666f TH\u226530\uff0c\u6050\u614c\u5171\u632f\u53ef\u66f4\u4f4e\uff09",
        "current_price": round(cur, 2),
        "action": action,
        "action_label": action_label or "",
        "drop_to_line_pct": round(drop_to_line, 1),
        "line_price": round(line_price, 2),
        "pct30_price": round(pct30_price, 2),
        "z0_price": z0_price,
        "pct_gap": round(pct_gap, 1),
        "z_gap": round(z_gap, 2),
        "th_gap": round(th_gap, 0),
        "th_score": th,
        "th_target": th_target,
        "regime": regime,
        "summary": summary,
        "bar_pct": round(bar, 0),
    }
