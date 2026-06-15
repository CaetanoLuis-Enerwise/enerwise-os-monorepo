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

echo [CHECK] Checking Enerwise API on http://127.0.0.1:8000
powershell -NoProfile -Command "try { $health = Invoke-RestMethod -Uri 'http://127.0.0.1:8000/health' -TimeoutSec 3; if ($health.status -eq 'active') { exit 0 } } catch {}; exit 1"
if errorlevel 1 (
  echo [START] Launching Enerwise API...
  start "Enerwise API" cmd /k "cd /d ""%~dp0"" && set PYTHONUTF8=1 && ""venv\Scripts\python.exe"" -m uvicorn app.main:app --reload --host 127.0.0.1 --port 8000"
) else (
  echo [OK] Enerwise API is already online.
)

echo [START] Launching Enerwise web app on http://localhost:8080
start "Enerwise Web" cmd /k "cd /d ""%~dp0personal-power-flow"" && npm run dev"

echo [WAIT] Waiting for the API health check...
powershell -NoProfile -Command "$deadline = (Get-Date).AddSeconds(90); do { try { $health = Invoke-RestMethod -Uri 'http://127.0.0.1:8000/health' -TimeoutSec 3; if ($health.status -eq 'active' -and $health.engine_mode -eq 'online') { exit 0 } } catch {}; Start-Sleep -Seconds 2 } while ((Get-Date) -lt $deadline); exit 1"
if errorlevel 1 goto :api_error

echo [OK] API and forecasting engine are online.
timeout /t 3 /nobreak >nul
start "" "http://localhost:8080/enerwise-demo"
exit /b 0

:api_error
echo.
echo Enerwise API did not become ready within 90 seconds.
echo Review the "Enerwise API" window for the exact error.
pause
exit /b 1

:error
echo.
echo Enerwise could not start. Review the error above.
pause
exit /b 1
