# -*- coding: utf-8 -*-
"""回放口径快照生成（Phase 0 回归护栏）。

读 data/item_backtest_full_2025.json，计算 aggregate + 月度（含去簇，与
references/j2_channel_monitor.py 同口径），写入 tests/snapshots/replay_v2.json。
test_smoke 的 t_replay_snapshot 断言当前回放与快照一致，防止回放产物/成本口径被无意改动。

用法（改动回放产物 / 成本口径后，人工确认新口径合理再运行）:
    python references/sync_replay_snapshot.py
"""
import io
import json
import sys
from pathlib import Path

BASE = Path(__file__).resolve().parent.parent
REPLAY = BASE / "data" / "item_backtest_full_2025.json"
OUT = BASE / "tests" / "snapshots" / "replay_v2.json"

sys.path.insert(0, str(BASE / "references"))
import j2_channel_monitor as _j2

AGG_KEYS = ("signals", "win14", "n14", "win14_pct", "avg14", "wavg14",
            "win30", "n30", "win30_pct", "avg30", "wavg30")


def main():
    replay = json.loads(io.open(REPLAY, encoding="utf-8").read())
    OUT.parent.mkdir(parents=True, exist_ok=True)
    snap = {
        "meta": "回放口径快照(Phase 0): aggregate+月度(含去簇) 与 j2_channel_monitor 同口径。"
                "改动回放产物/成本口径后重跑本脚本并人工确认。",
        "aggregate": {k: replay["aggregate"][k] for k in AGG_KEYS},
        "monthly": _j2._monthly(replay["signals"]),
    }
    with io.open(OUT, "w", encoding="utf-8", newline="\n") as f:
        json.dump(snap, f, ensure_ascii=False, indent=1)
    print("written:", OUT)


if __name__ == "__main__":
    main()