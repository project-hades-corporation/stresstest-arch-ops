@echo off
REM Start the Architecture Stress Platform without reinstalling dependencies.
setlocal EnableExtensions EnableDelayedExpansion

set "APP_DIR=%~dp0"
set "BACKEND_LOG=%TEMP%\arch_stress_backend.log"
set "FRONTEND_LOG=%TEMP%\arch_stress_frontend.log"
cd /d "%APP_DIR%"

echo === Architecture Stress Platform - start ===

if not exist "%APP_DIR%.venv\Scripts\python.exe" (
  echo ERROR: Python environment not found. Run setup.bat once first.
  exit /b 1
)
if not exist "%APP_DIR%frontend\node_modules\next\dist\bin\next" (
  echo ERROR: Frontend dependencies not found. Run setup.bat once first.
  exit /b 1
)
"%APP_DIR%.venv\Scripts\python.exe" -m uvicorn --version >nul 2>&1
if errorlevel 1 (
  echo ERROR: Backend dependencies are missing. Run setup.bat once to install them.
  exit /b 1
)

powershell -NoProfile -Command "try { if ((Invoke-WebRequest -UseBasicParsing -TimeoutSec 2 http://127.0.0.1:8000/health).StatusCode -eq 200) { exit 0 }; exit 1 } catch { exit 1 }" >nul 2>&1
if errorlevel 1 (
  "%APP_DIR%.venv\Scripts\python.exe" -c "import socket,sys; s=socket.socket(); s.settimeout(1); sys.exit(0 if s.connect_ex(('127.0.0.1',8000)) == 0 else 1)" >nul 2>&1
  if not errorlevel 1 (
    echo ERROR: Port 8000 is occupied, but the backend health check failed.
    echo Stop the process using port 8000, then run start.bat again.
    exit /b 1
  )
  echo Starting backend on :8000 ...
  start "Architecture Stress Backend" /B /D "%APP_DIR%" "%APP_DIR%.venv\Scripts\python.exe" -m uvicorn backend.main:app --host 0.0.0.0 --port 8000 >>"%BACKEND_LOG%" 2>&1
  if errorlevel 1 (
    echo ERROR: Could not start backend. See "%BACKEND_LOG%"
    exit /b 1
  )
) else (
  echo [OK] Backend is already running on :8000.
)

powershell -NoProfile -Command "try { if ((Invoke-WebRequest -UseBasicParsing -TimeoutSec 2 http://127.0.0.1:3000).StatusCode -eq 200) { exit 0 }; exit 1 } catch { exit 1 }" >nul 2>&1
if errorlevel 1 (
  "%APP_DIR%.venv\Scripts\python.exe" -c "import socket,sys; s=socket.socket(); s.settimeout(1); sys.exit(0 if s.connect_ex(('127.0.0.1',3000)) == 0 else 1)" >nul 2>&1
  if not errorlevel 1 (
    echo ERROR: Port 3000 is occupied, but the frontend health check failed.
    echo Stop the process using port 3000, then run start.bat again.
    exit /b 1
  )
  echo Starting frontend on :3000 ...
  start "Architecture Stress Frontend" /B /D "%APP_DIR%frontend" cmd /c "npm run dev -- --hostname 0.0.0.0" >>"%FRONTEND_LOG%" 2>&1
  if errorlevel 1 (
    echo ERROR: Could not start frontend. See "%FRONTEND_LOG%"
    exit /b 1
  )
) else (
  echo [OK] Frontend is already running on :3000.
)

echo Waiting for services...
set "BACKEND_READY=0"
set "FRONTEND_READY=0"
for /l %%I in (1,1,30) do (
  if "!BACKEND_READY!"=="0" (
    powershell -NoProfile -Command "try { if ((Invoke-WebRequest -UseBasicParsing -TimeoutSec 2 http://127.0.0.1:8000/health).StatusCode -eq 200) { exit 0 }; exit 1 } catch { exit 1 }" >nul 2>&1
    if not errorlevel 1 set "BACKEND_READY=1"
  )
  if "!FRONTEND_READY!"=="0" (
    powershell -NoProfile -Command "try { if ((Invoke-WebRequest -UseBasicParsing -TimeoutSec 2 http://127.0.0.1:3000).StatusCode -eq 200) { exit 0 }; exit 1 } catch { exit 1 }" >nul 2>&1
    if not errorlevel 1 set "FRONTEND_READY=1"
  )
  if "!BACKEND_READY!"=="1" if "!FRONTEND_READY!"=="1" goto :ready
  timeout /t 2 /nobreak >nul
)

if "!BACKEND_READY!"=="0" (
  echo ERROR: Backend did not become healthy. See "%BACKEND_LOG%"
  powershell -NoProfile -Command "Get-Content -Tail 30 '%BACKEND_LOG%'" 2>nul
  exit /b 1
)
if "!FRONTEND_READY!"=="0" (
  echo ERROR: Frontend did not become available. See "%FRONTEND_LOG%"
  powershell -NoProfile -Command "Get-Content -Tail 30 '%FRONTEND_LOG%'" 2>nul
  exit /b 1
)

:ready
echo [OK] Backend:  http://localhost:8000
echo [OK] Frontend: http://localhost:3000
echo Logs: "%BACKEND_LOG%" and "%FRONTEND_LOG%"
endlocal
