import sys, os

_project_root = os.path.dirname(os.path.abspath(__file__))
if _project_root not in sys.path:
    sys.path.insert(0, _project_root)

if __name__ == '__main__':
    import uvicorn
    # 2026-08-06 性能：启动时预热 DB schema（_init_schema 32 条 DDL 首次执行约 1~3s），
    # 避免首个大盘刷新请求承担一次性建表成本（get_conn 已按路径缓存，预热后首刷即热）。
    try:
        from pipeline import db
        db.get_conn().close()
    except Exception as _e:
        print(f"DB schema warm-up skipped: {_e}")
    print("Starting CS-Market server on http://127.0.0.1:8000")
    print(f"Python: {sys.executable}")
    print(f"Project: {_project_root}")
    # 2026-08-09 ?????? pipeline/webapp ????????????????
    # ??? watchfiles???? .py ?????????????
    uvicorn.run('webapp.main:app', host='127.0.0.1', port=8000, log_level='info', reload=True)
