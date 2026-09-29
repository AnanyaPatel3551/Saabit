# Saabit

Ask questions about your sales file and get verified answers. See `docs/PRD.md` for the full spec.

## Run locally (Windows, PowerShell)

```powershell
py -3.11 -m venv backend\.venv
backend\.venv\Scripts\python.exe -m pip install -r backend\requirements.txt
cd frontend; npm install; cd ..

.\tasks.ps1 test          # pytest
.\tasks.ps1 lint          # ruff check
.\tasks.ps1 dev-backend   # API on http://localhost:8000
.\tasks.ps1 dev-frontend  # UI on http://localhost:5173, /api proxied to :8000
```
