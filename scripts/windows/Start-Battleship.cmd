@echo off
setlocal

set "SCRIPT_DIR=%~dp0"
for %%I in ("%SCRIPT_DIR%..\..") do set "ROOT=%%~fI"

set "LOG_DIR=%ROOT%\logs\startup"
if not exist "%LOG_DIR%" mkdir "%LOG_DIR%"

set "TS="
for /f %%I in ('powershell -NoProfile -Command "(Get-Date).ToString('yyyyMMdd_HHmmss')"') do set "TS=%%I"
if "%TS%"=="" set "TS=%RANDOM%"

set "LOG_FILE=%LOG_DIR%\start_%TS%.log"
set "BACKEND_LOG=%LOG_DIR%\backend_%TS%.log"
set "FRONTEND_LOG=%LOG_DIR%\frontend_%TS%.log"

call :main >> "%LOG_FILE%" 2>&1
set "EXIT_CODE=%ERRORLEVEL%"

if not "%EXIT_CODE%"=="0" (
  echo [Battleship] Startup failed. See log: "%LOG_FILE%"
  echo [Battleship] Press any key to close...
  pause >nul
  exit /b %EXIT_CODE%
)

echo [Battleship] Startup command finished. Log: "%LOG_FILE%"
exit /b 0

:main
echo [Battleship] Root: %ROOT%
echo [Battleship] Log: %LOG_FILE%

echo [Battleship] Checking packaged desktop build...
if exist "%ROOT%\desktop\src-tauri\target\release\battleship-desktop.exe" (
  echo [Battleship] Starting packaged desktop build...
  start "" "%ROOT%\desktop\src-tauri\target\release\battleship-desktop.exe"
  exit /b 0
)

if exist "%ROOT%\desktop\src-tauri\target\release\Battleship.exe" (
  echo [Battleship] Starting packaged desktop build...
  start "" "%ROOT%\desktop\src-tauri\target\release\Battleship.exe"
  exit /b 0
)

where cargo >nul 2>nul
if %errorlevel%==0 (
  echo [Battleship] Cargo found. Using desktop dev mode.

  if not exist "%ROOT%\desktop\node_modules" (
    echo [Battleship] Installing desktop dependencies...
    call npm --prefix "%ROOT%\desktop" ci
    if errorlevel 1 exit /b 1
  )

  if not exist "%ROOT%\frontend\node_modules" (
    echo [Battleship] Installing frontend dependencies...
    call npm --prefix "%ROOT%\frontend" ci
    if errorlevel 1 exit /b 1
  )

  if not exist "%ROOT%\backend\.venv\Scripts\python.exe" (
    echo [Battleship] Creating backend venv...
    py -3 -m venv "%ROOT%\backend\.venv"
    if errorlevel 1 exit /b 1
  )

  echo [Battleship] Installing backend dependencies...
  call "%ROOT%\backend\.venv\Scripts\python.exe" -m pip install -e "%ROOT%\backend[dev]"
  if errorlevel 1 exit /b 1

  set "BATTLESHIP_BACKEND_DIR=%ROOT%\backend"
  set "BATTLESHIP_PYTHON=%ROOT%\backend\.venv\Scripts\python.exe"

  echo [Battleship] Starting desktop dev mode...
  call npm --prefix "%ROOT%\desktop" run dev
  exit /b %ERRORLEVEL%
)

echo [Battleship] Cargo not found. Fallback to web mode.

if not exist "%ROOT%\backend\.venv\Scripts\python.exe" (
  echo [Battleship] Creating backend venv...
  py -3 -m venv "%ROOT%\backend\.venv"
  if errorlevel 1 exit /b 1
)

echo [Battleship] Installing backend dependencies...
call "%ROOT%\backend\.venv\Scripts\python.exe" -m pip install -e "%ROOT%\backend[dev]"
if errorlevel 1 exit /b 1

if not exist "%ROOT%\frontend\node_modules" (
  echo [Battleship] Installing frontend dependencies...
  call npm --prefix "%ROOT%\frontend" ci
  if errorlevel 1 exit /b 1
)

echo [Battleship] Starting backend. Log: %BACKEND_LOG%
start "Battleship Backend" cmd /k "cd /d \"%ROOT%\backend\" && .venv\Scripts\python.exe -m uvicorn app.main:app --host 127.0.0.1 --port 8000 1>>\"%BACKEND_LOG%\" 2>>&1"

echo [Battleship] Starting frontend. Log: %FRONTEND_LOG%
start "Battleship Frontend" cmd /k "cd /d \"%ROOT%\frontend\" && npm run dev 1>>\"%FRONTEND_LOG%\" 2>>&1"

timeout /t 3 >nul
start "" "http://localhost:5173"
exit /b 0
