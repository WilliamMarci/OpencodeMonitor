@echo off
rem Convenience launcher for Windows.
setlocal
cd /d "%~dp0"

if not exist .venv (
  python -m venv .venv
)
.venv\Scripts\python -c "import PySide6" >nul 2>&1
if errorlevel 1 (
  .venv\Scripts\pip install -q -r requirements.txt
)
start "" .venv\Scripts\pythonw main.py %*
