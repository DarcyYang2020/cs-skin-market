# -*- coding: utf-8 -*-
"""只读：全族现状快照——键/优先级/仓位/默认开关/时期禁发。"""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import pipeline.item_analysis as ia  # noqa: E402

rows = []
for fam in sorted(ia.SIGNAL_FAMILIES, key=lambda f: -f.priority):
    env_on = None
    for k in ("CS_ENGINE_C_WAVE", "CS_ENGINE_D_ACCUM", "CS_ENGINE_RISE_ACCUM",
              "CS_ENGINE_RISE_CONTRACT", "CS_ENGINE_XISHOU_MID", "CS_ENGINE_RS_ACCUM",
              "CS_ENGINE_CT_ACCUM"):
        if fam.key in ("second_wave",) and k == "CS_ENGINE_C_WAVE":
            env_on = k
        elif fam.key == "volatile_accum" and k == "CS_ENGINE_D_ACCUM":
            env_on = k
        elif fam.key == "rise_accum" and k == "CS_ENGINE_RISE_ACCUM":
            env_on = k
        elif fam.key == "rise_contract" and k == "CS_ENGINE_RISE_CONTRACT":
            env_on = k
        elif fam.key == "xishou_mid" and k == "CS_ENGINE_XISHOU_MID":
            env_on = k
        elif fam.key == "rs_accum" and k == "CS_ENGINE_RS_ACCUM":
            env_on = k
        elif fam.key == "ct_accum" and k == "CS_ENGINE_CT_ACCUM":
            env_on = k
    rows.append({"key": fam.key, "label": fam.label, "priority": fam.priority,
                 "limit": fam.limit, "env": env_on,
                 "period_ban": ia.PERIOD_ROUTE_BAN.get(fam.key, None)})
print(json.dumps(rows, ensure_ascii=False, indent=1))
