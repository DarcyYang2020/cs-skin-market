# -*- coding: utf-8 -*-
"""运维④ 2026-08-20：误删恢复遗漏——重建两个派生回放库。

背景：283 文件误删事件中，data/replay_hybrid.db 与 data/replay_cycle_win.db
为 git 未跟踪的派生库，checkout 覆盖不到；原构建依赖 market.db.bak-p0-*（已丢失）
与 csQAQ 联网回填（backfill_cycle_window.py / backfill_full_pool.py），无法原样复刻。

重建方式（最小重建，结构保真）：
- 源：生产库 data/market.db（只读，不修改）
- 目标：data/replay_hybrid.db、data/replay_cycle_win.db
- 复制表：items / price_history / market_index（DDL+索引保真，数据全量复制）
- 依赖确认：test_smoke 两项（period_boundary_recheck / family_feature_card）
  与 references/family_feature_card.py 只读 market_index(date,value)，生产 3 年
  同口径数据（2023-11-17~2026-08-20，1008 行）即可满足；
  price_history 深度=生产 365 天保留策略（原 replay 为 3 年，需联网回填才可达，
  属②研究域决策，此处标注不越权）。

产物审计：输出各表行数与 market_index 范围。
"""
import os
import sqlite3

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SRC = os.path.join(ROOT, "data", "market.db")
DBS = ["replay_hybrid.db", "replay_cycle_win.db"]
TABLES = ["items", "price_history", "market_index"]

src = sqlite3.connect(SRC)
src.row_factory = sqlite3.Row

for dbname in DBS:
    dst_path = os.path.join(ROOT, "data", dbname)
    if os.path.exists(dst_path) and os.path.getsize(dst_path) > 0:
        # 幂等重建：覆盖前备份旧版到 _ops_recovery 目录
        import shutil
        bk_dir = os.path.join(ROOT, "data", "_ops_recovery_2026-08-20")
        os.makedirs(bk_dir, exist_ok=True)
        bk = os.path.join(bk_dir, f"{dbname}.pre-rebuild")
        shutil.copy2(dst_path, bk)
        print(f"[backup] {dbname} ({os.path.getsize(dst_path)}B) -> {bk}")
    dst = sqlite3.connect(dst_path)
    # 幂等：清空目标库内三表（DROP 级联删索引），再按生产 DDL 重建
    for t in TABLES:
        dst.execute(f"DROP TABLE IF EXISTS {t}")
    dst.commit()
    # 1) 复制表 DDL
    for r in src.execute(
        "SELECT name, sql FROM sqlite_master WHERE type='table' AND name IN "
        "('items','price_history','market_index')"
    ):
        dst.execute(r["sql"])
    # 2) 复制索引 DDL（结构保真）
    idx_ok = idx_skip = 0
    for r in src.execute(
        "SELECT name, sql FROM sqlite_master WHERE type='index' AND tbl_name IN "
        "('items','price_history','market_index') AND sql IS NOT NULL"
    ):
        try:
            dst.execute(r["sql"])
            idx_ok += 1
        except Exception as e:  # noqa: BLE001
            idx_skip += 1
            print(f"  [idx skip] {r['name']}: {e}")
    dst.commit()
    # 3) 复制数据（ATTACH 只读源，不改生产库）
    dst.execute("ATTACH DATABASE ? AS src", (SRC,))
    for t in TABLES:
        cols = [r["name"] for r in src.execute(f"PRAGMA table_info({t})")]
        colstr = ",".join(cols)
        dst.execute(f"INSERT INTO {t} ({colstr}) SELECT {colstr} FROM src.{t}")
    dst.commit()
    # 4) 审计
    print(f"=== {dbname} ===")
    for t in TABLES:
        n = dst.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0]
        print(f"  {t}: {n} 行")
    mi = dst.execute(
        "SELECT MIN(date), MAX(date), COUNT(*) FROM market_index"
    ).fetchone()
    print(f"  market_index: {mi[0]} ~ {mi[1]} ({mi[2]} 行)")
    ph = dst.execute(
        "SELECT MIN(date), MAX(date), COUNT(*) FROM price_history"
    ).fetchone()
    print(f"  price_history: {ph[0]} ~ {ph[1]} ({ph[2]} 行) [生产 365 天深度，非原 3 年]")
    print(f"  索引: {idx_ok} ok / {idx_skip} skip")
    dst.close()

src.close()
print("\n重建完成：两库已从生产库重建（结构保真，生产库只读未动）。")
