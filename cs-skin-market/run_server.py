import sys, os

_project_root = os.path.dirname(os.path.abspath(__file__))
if _project_root not in sys.path:
    sys.path.insert(0, _project_root)

if __name__ == '__main__':
    import uvicorn
    print(f"Starting CS-Market server on http://127.0.0.1:8000")
    print(f"Python: {sys.executable}")
    print(f"Project: {_project_root}")
    uvicorn.run('webapp.main:app', host='127.0.0.1', port=8000, log_level='info')
