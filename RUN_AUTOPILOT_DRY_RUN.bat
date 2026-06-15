@echo off
setlocal
cd /d "%~dp0"

if not exist "venv\Scripts\python.exe" (
  echo Python environment not found. Run START_ENERWISE.bat first.
  pause
  exit /b 1
)

set PYTHONUTF8=1
"venv\Scripts\python.exe" -m app.control_loop --interval-minutes 30
