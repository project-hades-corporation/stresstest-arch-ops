@echo off
setlocal EnableExtensions

set "APP_DIR=%~dp0"
cd /d "%APP_DIR%"
if errorlevel 1 (
  echo ERROR: Could not open the project directory.
  exit /b 1
)

echo === Architecture Stress Platform setup ===

set "PYTHON_CMD=python"
python -c "import sys; sys.exit(0 if sys.version_info >= (3, 10) else 1)" >nul 2>&1
if errorlevel 1 set "PYTHON_CMD=py -3"
%PYTHON_CMD% -c "import sys; sys.exit(0 if sys.version_info >= (3, 10) else 1)" >nul 2>&1
if errorlevel 1 (
  echo ERROR: Python 3.10 or newer is required.
  exit /b 1
)
for /f "delims=" %%V in ('%PYTHON_CMD% --version 2^>^&1') do echo [OK] %%V

where node >nul 2>&1
if errorlevel 1 (
  echo ERROR: Node.js 18 or newer is required.
  exit /b 1
)
node -e "process.exit(Number(process.versions.node.split('.')[0]) >= 18 ? 0 : 1)" >nul 2>&1
if errorlevel 1 (
  echo ERROR: Node.js 18 or newer is required.
  exit /b 1
)
where npm >nul 2>&1
if errorlevel 1 (
  echo ERROR: npm is required. Install Node.js 18 or newer, then retry.
  exit /b 1
)
for /f "delims=" %%V in ('node --version 2^>^&1') do echo [OK] Node.js %%V

if not exist "%APP_DIR%.venv\Scripts\python.exe" (
  echo Creating Python virtual environment...
  %PYTHON_CMD% -m venv "%APP_DIR%.venv"
  if errorlevel 1 (
    echo ERROR: Could not create the Python virtual environment.
    exit /b 1
  )
) else (
  "%APP_DIR%.venv\Scripts\python.exe" -c "import sys; sys.exit(0 if sys.version_info >= (3, 10) else 1)" >nul 2>&1
  if errorlevel 1 (
    echo ERROR: The existing .venv does not use Python 3.10 or newer.
    echo Rename or remove .venv, then run setup.bat again.
    exit /b 1
  )
  echo Reusing existing Python virtual environment.
)

echo Installing Python dependencies...
"%APP_DIR%.venv\Scripts\python.exe" -m pip install -r "%APP_DIR%requirements.txt"
if errorlevel 1 (
  echo ERROR: Python dependency installation failed.
  exit /b 1
)

echo Installing frontend dependencies...
pushd "%APP_DIR%frontend"
if errorlevel 1 (
  echo ERROR: Could not open the frontend directory.
  exit /b 1
)
call npm install
set "NPM_STATUS=%ERRORLEVEL%"
popd
if not "%NPM_STATUS%"=="0" (
  echo ERROR: Frontend dependency installation failed.
  exit /b 1
)

echo.
echo Setup complete! Open this workspace in your IDE, open your agent chat / Copilot tab, and type: 'Run the stress-arch skill to analyze my architecture.'
endlocal
