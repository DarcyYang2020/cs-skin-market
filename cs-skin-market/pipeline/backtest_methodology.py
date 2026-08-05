# -*- coding: utf-8 -*-
"""回测方法学工具（A2 工作流，只读分析，纯函数，无引擎依赖）。
解决同一痛点：信号高度集中在少数事件日（如 2026-05-22~05-26 单簇 42/88），按信号条数统计的胜率容易被单一事件自证。本模块提供三个可复用检验：
- signal_cluster_report(): 信号时间聚类，量化事件集中度；
- walk_forward_split():    按时间序切分 train/test，比较样本内外胜率；
- permutation_baseline():  符号置换检验，估计“随机也能达到该胜率”的经验 p 值。
设计约束：
- 不改任何信号引擎/回测口径，只对信号日期与收益序列做统计；
- 输入输出均为纯 Python 对象（dict/list），不依赖 DB 或引擎，可在回测报告、测试与外部脚本中直接复用。
"""
import random
from collections import Counter
from datetime import datetime


def _parse_date(d):
    """格式为 YYYY-MM-DD；输入非法时抛 ValueError。"""
    return datetime.strptime(d, "%Y-%m-%d").date()


def _win_stats(returns):
    """returns: 数值列表 -> (n, wins, win_rate, avg)。空列表返回 (0, 0, None, None)。"""
    vals = [float(x) for x in returns]
    n = len(vals)
    if n == 0:
        return 0, 0, None, None
    wins = sum(1 for v in vals if v > 0)
    return n, wins, wins / n, sum(vals) / n


def signal_cluster_report(dates, window=3):
    """信号时间聚类报告。

    ±window 天内算同一事件簇：排序后连续日期 gap <= window 归入同簇
    （同一日期多条信号按日期计数）。输出信号数、簇数、最大簇占比、
    去重后事件级数量；当单簇占比 > 50% 或有效事件日 < 5 时给出 warning。

    参数:
        dates:  信号日期列表（YYYY-MM-DD str，可含重复日期）。
        window: 聚类窗口（天），默认 3。

    返回:
        dict: signal_count/unique_dates/cluster_count/event_count/
              max_cluster_share/max_cluster/clusters/warnings/flagged。
    """
    if not dates:
        return {
            "window": window, "signal_count": 0, "unique_dates": 0,
            "cluster_count": 0, "event_count": 0, "max_cluster_share": 0.0,
            "max_cluster": None, "clusters": [], "warnings": ["无信号日期"],
            "flagged": True,
        }
    counts = Counter(dates)
    uniq = sorted(counts)
    clusters = []
    for d in uniq:
        if not clusters or (_parse_date(d) - _parse_date(clusters[-1]["end"])).days > window:
            clusters.append({"start": d, "end": d, "dates": [d]})
        else:
            clusters[-1]["end"] = d
            clusters[-1]["dates"].append(d)
    total = sum(counts.values())
    for idx, c in enumerate(clusters):
        c["signals"] = sum(counts[x] for x in c["dates"])
        c["share"] = round(c["signals"] / total, 4)
        c["index"] = idx
    max_cluster = max(clusters, key=lambda c: c["signals"])
    max_share = max_cluster["signals"] / total
    event_count = len(clusters)
    warnings = []
    if max_share > 0.5:
        warnings.append("单簇占比 %.1f%% > 50%%，胜率由单一事件主导，外推性存疑" % (max_share * 100))
    if event_count < 5:
        warnings.append("有效事件日 %d < 5，独立样本不足" % event_count)
    if not warnings and total > 1:
        top2 = sum(c["signals"] for c in sorted(clusters, key=lambda c: -c["signals"])[:2])
        if top2 / total > 0.8:
            warnings.append("前两大事件簇合计 %.1f%% > 80%%，胜率集中于少数行情段" % (top2 / total * 100))
    return {
        "window": window, "signal_count": total, "unique_dates": len(uniq),
        "cluster_count": event_count, "event_count": event_count,
        "max_cluster_share": round(max_share, 4),
        "max_cluster": {"start": max_cluster["start"], "end": max_cluster["end"],
                        "signals": max_cluster["signals"],
                        "share": round(max_cluster["signals"] / total, 4)},
        "clusters": clusters, "warnings": warnings, "flagged": bool(warnings),
    }


def walk_forward_split(signal_records, anchor_ratio=0.7, return_field="fwd14",
                       min_samples=5):
    """按时间序切分 train/test，返回两段胜率/均值/样本数。

    记录按日期升序排列，在 anchor_ratio 处切分；若边界处同日，
    自动后移切点直到 test 段完全在 train 段之后（严格时序）。

    参数:
        signal_records: 信号记录列表，每项为含 date 与 return_field 的 dict。
        anchor_ratio:   train 占比目标，默认 0.7。
        return_field:   收益字段名，默认 "fwd14"。
        min_samples:    两段各自最小样本数，低于则 valid=False。

    返回:
        dict: anchor_ratio/n/split_index/train/test/strict_after/valid/reason。
    """
    records = sorted(signal_records, key=lambda r: r["date"])
    n = len(records)
    if n == 0:
        return {"anchor_ratio": anchor_ratio, "n": 0, "split_index": 0,
                "train": None, "test": None, "strict_after": True,
                "valid": False, "reason": "无信号记录"}
    split = int(round(n * anchor_ratio))
    split = max(1, min(n, split))
    while split < n and records[split]["date"] == records[split - 1]["date"]:
        split += 1

    def seg_stats(seg):
        if not seg:
            return None
        rets = [r.get(return_field) for r in seg if r.get(return_field) is not None]
        cnt, wins, wr, avg = _win_stats(rets)
        return {"n": len(seg), "n_with_return": cnt, "wins": wins,
                "win_rate": round(wr, 4) if wr is not None else None,
                "avg": round(avg, 4) if avg is not None else None,
                "date_range": [seg[0]["date"], seg[-1]["date"]]}

    train, test = seg_stats(records[:split]), seg_stats(records[split:])
    strict_after = bool(test and train and test["date_range"][0] > train["date_range"][1])
    reasons = []
    if not strict_after:
        reasons.append("test 段未完全晚于 train 段")
    if train is None or train["n"] < min_samples:
        reasons.append("train 样本不足 min_samples=%d" % min_samples)
    if test is None or test["n"] < min_samples:
        reasons.append("test 样本不足 min_samples=%d" % min_samples)
    return {"anchor_ratio": anchor_ratio, "n": n, "split_index": split,
            "train": train, "test": test, "strict_after": strict_after,
            "valid": not reasons, "reason": "; ".join(reasons) or None}


def permutation_baseline(fwd_returns, n_perm=1000, seed=42):
    """符号置换检验：估计随机符号下达到观察胜率的经验 p 值（单尾）。

    对每条收益以 50% 概率翻转符号（保留幅度），重算胜率；
    p 值 = (置换胜率 >= 观察胜率的次数 + 1) / (n_perm + 1)。
    p 值越小，说明观察胜率越不可能由随机符号产生。

    参数:
        fwd_returns: 前向收益数值列表（可含 None，自动剔除）。
        n_perm:      置换次数，默认 1000。
        seed:        随机种子，保证可复现。

    返回:
        dict: n/n_perm/method/observed_win_rate/observed_avg/
              perm_mean_win_rate/perm_std_win_rate/perm_p95_win_rate/
              hits/p_value。
    """
    returns = [float(x) for x in fwd_returns if x is not None]
    n = len(returns)
    rng = random.Random(seed)
    if n == 0:
        return {"n": 0, "n_perm": n_perm, "method": "sign-flip",
                "observed_win_rate": None, "observed_avg": None,
                "perm_mean_win_rate": None, "perm_std_win_rate": None,
                "perm_p95_win_rate": None, "hits": 0, "p_value": None}
    _, _, observed_wr, observed_avg = _win_stats(returns)
    perm_wr = []
    hits = 0
    for _ in range(n_perm):
        flipped = [v if rng.random() < 0.5 else -v for v in returns]
        _, _, wr, _ = _win_stats(flipped)
        perm_wr.append(wr)
        if wr >= observed_wr - 1e-12:
            hits += 1
    perm_mean = sum(perm_wr) / len(perm_wr)
    perm_std = (sum((x - perm_mean) ** 2 for x in perm_wr) / len(perm_wr)) ** 0.5
    perm_sorted = sorted(perm_wr)
    p95 = perm_sorted[int(len(perm_sorted) * 0.95) - 1]
    return {
        "n": n, "n_perm": n_perm, "method": "sign-flip",
        "observed_win_rate": round(observed_wr, 4),
        "observed_avg": round(observed_avg, 4),
        "perm_mean_win_rate": round(perm_mean, 4),
        "perm_std_win_rate": round(perm_std, 4),
        "perm_p95_win_rate": round(p95, 4),
        "hits": hits, "p_value": round((hits + 1) / (n_perm + 1), 6),
    }
