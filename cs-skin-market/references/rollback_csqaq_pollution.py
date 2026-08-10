# -*- coding: utf-8 -*-
"""csQAQ 故障期污染数据回滚（2026-08-10 21:35）：
16 品 8/10 行 price_rmb/in_sale_count 回滚为 8/9 真实值（临时替代）。
csQAQ 恢复后须 force 重采覆盖。备份: data/market.db.bak-csqaq-20260810-2130
"""
import json, io, sqlite3, datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DB = ROOT / "data" / "market.db"
LOG = ROOT / "data" / "caliber_override_log.jsonl"

POLLUTED = [2, 6, 9, 18, 23, 27, 33, 37, 44, 58, 60, 63, 68, 69, 82, 94]

conn = sqlite3.connect(DB)
conn.row_factory = sqlite3.Row
updated = []
for iid in POLLUTED:
    r9 = conn.execute("SELECT price_rmb, in_sale_count FROM price_history WHERE item_id=? AND date='2026-08-09'", (iid,)).fetchone()
    if not r9:
        print("skip", iid, "无 8/9 行")
        continue
    before = conn.execute("SELECT price_rmb, in_sale_count FROM price_history WHERE item_id=? AND date='2026-08-10'", (iid,)).fetchone()
    conn.execute("UPDATE price_history SET price_rmb=?, in_sale_count=? WHERE item_id=? AND date='2026-08-10'",
                 (r9["price_rmb"], r9["in_sale_count"], iid))
    updated.append({"item_id": iid, "before": dict(before) if before else None, "after": dict(r9)})
conn.commit()
conn.close()

rec = {
    "ts": datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
    "kind": "csqaq_failure_rollback",
    "detail": f"csQAQ 单品API 500 期间(18:23-18:31 采集)写入异常数据，16 品 8/10 行回滚至 8/9 值；备份 market.db.bak-csqaq-20260810-2130；恢复后须 force 重采",
    "items": [u["item_id"] for u in updated],
}
with io.open(LOG, "a", encoding="utf-8") as f:
    f.write(json.dumps(rec, ensure_ascii=False) + "\n")
print("回滚完成:", len(updated), "品; 留痕已写")
for u in updated:
    print(u["item_id"], "before", u["before"], "-> after", u["after"])