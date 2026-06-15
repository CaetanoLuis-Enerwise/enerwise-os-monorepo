@echo off
setlocal
title Enerwise OS
cd /d "%~dp0"

if not exist "venv\Scripts\python.exe" (
  echo [SETUP] Creating Python virtual environment...
  python -m venv venv
  if errorlevel 1 goto :error
)

echo [SETUP] Checking Python dependencies...
"venv\Scripts\python.exe" -m pip install -r requirements.txt
if errorlevel 1 goto :error

if not exist "personal-power-flow\node_modules" (
  echo [SETUP] Installing frontend dependencies...
  pushd "personal-power-flow"
  call npm install
  if errorlevel 1 (
    popd
    goto :error
  )
  popd
)

echo [START] Launching Enerwise API on http://127.0.0.1:8000
start "Enerwise API" cmd /k "cd /d ""%~dp0"" && set PYTHONUTF8=1 && ""venv\Scripts\python.exe"" -m uvicorn app.main:app --reload --host 127.0.0.1 --port 8000"

echo [START] Launching Enerwise web app on http://localhost:8080
start "Enerwise Web" cmd /k "cd /d ""%~dp0personal-power-flow"" && npm run dev"

echo [WAIT] Waiting for local services...
timeout /t 5 /nobreak >nul
start "" "http://localhost:8080/enerwise-demo"
exit /b 0

:error
echo.
echo Enerwise could not start. Review the error above.
pause
exit /b 1
