# -*- coding: utf-8 -*-
"""族特征卡实盘漂移监测（第一批 2026-08-16 骨架）。

实盘信号（market.db signal_tracking，net14/net30 已回填）按族聚合，与族特征卡
（data/family_feature_cards.json，三年回放口径）对照。漂移阈值**预注册固定**（监测三档，
非引擎参数）：n_live≥10 且 (win≤card−15pp 或 avg≤card−5pp) → WATCH；n_live≥20 → DECAY。
输出 data/family_drift.json（接入 C 通道展示；每日任务可调用）。
"""
import io
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from pipeline import db  # noqa: E402

CARDS = ROOT / "data" / "family_feature_cards.json"
OUT = ROOT / "data" / "family_drift.json"

# 预注册监测阈值（固定；如需调整须先改此处再跑，并记录理由）
MIN_N_WATCH = 10
MIN_N_DECAY = 20
WIN_GAP_PP = 15.0
AVG_GAP_PP = 5.0


def live_stats(conn):
    rows = conn.execute(
        "SELECT family, net14, net30 FROM signal_tracking "
        "WHERE family IS NOT NULL AND family != '' AND net14 IS NOT NULL").fetchall()
    fam = {}
    for r in rows:
        fam.setdefault(r["family"], []).append(r["net14"])
    out = {}
    for k, xs in fam.items():
        n = len(xs)
        out[k] = {"n": n,
                  "win": round(100.0 * sum(1 for x in xs if x > 0) / n, 1) if n else None,
                  "avg": round(sum(xs) / n, 2) if n else None}
    return out


def check_drift(live=None, cards_path=None):
    cards_path = Path(cards_path) if cards_path else CARDS
    if not cards_path.exists():
        return {"error": "family_feature_cards.json 缺失，先跑 family_feature_card.py"}
    cards = json.load(io.open(cards_path, encoding="utf-8"))["families"]
    if live is None:
        conn = db.get_conn()
        try:
            live = live_stats(conn)
        finally:
            conn.close()
    drift = {}
    for fam_key, card in cards.items():
        lv = live.get(fam_key, {"n": 0, "win": None, "avg": None})
        n = lv["n"]
        h14 = card["horizons"].get("14") or {}
        flag = None
        if n >= MIN_N_WATCH and h14.get("win") is not None and lv["win"] is not None:
            win_gap = lv["win"] - h14["win"]
            avg_gap = (lv["avg"] - h14["avg"]) if (lv["avg"] is not None and h14["avg"] is not None) else 0.0
            if win_gap <= -WIN_GAP_PP or avg_gap <= -AVG_GAP_PP:
                flag = "DECAY" if n >= MIN_N_DECAY else "WATCH"
        drift[fam_key] = {"live_n": n, "live_win": lv["win"], "live_avg": lv["avg"],
                          "card_win14": h14.get("win"), "card_avg14": h14.get("avg"),
                          "flag": flag}
    out = {"generated": __import__("datetime").datetime.now().isoformat(timespec="minutes"),
           "thresholds": {"min_n_watch": MIN_N_WATCH, "min_n_decay": MIN_N_DECAY,
                          "win_gap_pp": WIN_GAP_PP, "avg_gap_pp": AVG_GAP_PP},
           "families": drift}
    with io.open(OUT, "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, indent=1)
    return out


def main():
    out = check_drift()
    for k, v in out.get("families", {}).items():
        if v["live_n"]:
            print("%-16s live_n=%d live_win=%s card_win=%s -> %s" % (
                k, v["live_n"], v["live_win"], v["card_win14"], v["flag"]))
    print("wrote", OUT)


if __name__ == "__main__":
    main()
