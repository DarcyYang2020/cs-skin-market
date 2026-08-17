# -*- coding: utf-8 -*-
"""族特征卡聚合（第一批 2026-08-16）：从官方回放产物按族产出历史特征卡。

纯聚合、零拟合参数：期限 14/30/60/90/180 为固定报告档；做 T 参考=前 7/14/21 日路径峰值中位数；
五时期分层（2026-08-16 起）= market_context.state_bucket（chg180×chg30，替代原 bull/nonbull 牛熊拆分）。
族键与 signal_tracking.family_key_for_label 同源。
输出 data/family_feature_cards.json（族特征卡唯一事实源，供单品报告与漂移监测引用）。
"""
import io
import json
import os
import sqlite3
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from pipeline.signal_tracking import family_key_for_label  # noqa: E402
from pipeline.market_context import state_bucket  # noqa: E402

REPLAY = ROOT / "data" / "_exp_cycle_replay_2026.json"
OUT = ROOT / "data" / "family_feature_cards.json"
HORIZONS = (14, 30, 60, 90, 180)
PERIODS = ("P恐慌深跌", "S1牛市上行", "S2牛市回调", "S3弱市阴跌", "S4弱市反弹")


def _win_avg(vals):
    n = len(vals)
    if n == 0:
        return {"n": 0, "win": None, "avg": None}
    return {"n": n,
            "win": round(100.0 * sum(1 for v in vals if v > 0) / n, 1),
            "avg": round(sum(vals) / n, 2)}


def build_cards(replay_path=None, out_path=None):
    replay_path = Path(replay_path) if replay_path else REPLAY
    out_path = Path(out_path) if out_path else OUT
    d = json.load(io.open(replay_path, encoding="utf-8"))
    fam = {}
    for s in d.get("signals", []):
        fwd = s.get("fwd_series") or []
        if not fwd:
            continue
        key = family_key_for_label(s.get("action_label"))
        fam.setdefault(key, []).append({"date": s["date"], "fwd": fwd, "entry": s.get("entry_price")})
    # mkt_chg180 / mkt_chg30 每信号日（replay DB）——大盘五时期分层
    _prev_env = os.environ.get("CS_MODEL_DB")
    os.environ["CS_MODEL_DB"] = str(ROOT / "data" / "replay_cycle_win.db")
    try:
        c = sqlite3.connect(os.environ["CS_MODEL_DB"])
        c.row_factory = sqlite3.Row
        mrows = c.execute("SELECT date, value FROM market_index ORDER BY date").fetchall()
        c.close()
    finally:
        if _prev_env is None:
            os.environ.pop("CS_MODEL_DB", None)
        else:
            os.environ["CS_MODEL_DB"] = _prev_env
    mdates = [r["date"] for r in mrows]
    mvals = [r["value"] for r in mrows]
    m180, m30 = {}, {}
    for i in range(180, len(mvals)):
        m180[mdates[i]] = (mvals[i] / mvals[i - 180] - 1) * 100
    for i in range(30, len(mvals)):
        m30[mdates[i]] = (mvals[i] / mvals[i - 30] - 1) * 100

    cards = {}
    for key, sigs in fam.items():
        horizons = {}
        for h in HORIZONS:
            vals = [(s["fwd"][h - 1] / s["entry"] - 1.0) * 100 - 2.0 for s in sigs if len(s["fwd"]) >= h]
            horizons[str(h)] = _win_avg(vals)
        # 做 T 参考：前 7/14/21 日路径峰值（相对入场，扣 2%）
        peaks = {}
        for k in (7, 14, 21):
            xs = []
            for s in sigs:
                if len(s["fwd"]) >= k:
                    xs.append((max(s["fwd"][:k]) / s["entry"] - 1.0) * 100 - 2.0)
            if xs:
                xs.sort()
                peaks[str(k)] = {"n": len(xs), "median_peak_pct": round(xs[len(xs) // 2], 2)}
        # 大盘五时期分层（net14/30，2026-08-16 起；样本不足期由展示层降级）
        split = {}
        for p in PERIODS:
            sub = [s for s in sigs if state_bucket(m180.get(s["date"]), m30.get(s["date"])) == p]
            h14 = [(s["fwd"][13] / s["entry"] - 1.0) * 100 - 2.0 for s in sub if len(s["fwd"]) >= 14]
            h30 = [(s["fwd"][29] / s["entry"] - 1.0) * 100 - 2.0 for s in sub if len(s["fwd"]) >= 30]
            split[p] = {"net14": _win_avg(h14), "net30": _win_avg(h30)}
        cards[key] = {"n": len(sigs), "horizons": horizons, "t_peaks": peaks, "period": split}
    out = {"source": str(replay_path), "generated": __import__("datetime").datetime.now().isoformat(timespec="minutes"),
           "families": cards}
    with io.open(out_path, "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, indent=1)
    return out


def main():
    out = build_cards()
    for key, card in out["families"].items():
        h14 = card["horizons"]["14"]
        h60 = card["horizons"]["60"]
        h180 = card["horizons"]["180"]
        print("%-16s n=%3d | 14d %s | 60d %s | 180d %s" % (
            key, card["n"], h14["win"], h60["win"], h180["win"]))
    print("wrote", OUT)


if __name__ == "__main__":
    main()
