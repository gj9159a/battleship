@echo off
setlocal enabledelayedexpansion

set "SCRIPT_DIR=%~dp0"
for %%I in ("%SCRIPT_DIR%..\..") do set "ROOT=%%~fI"

cd /d "%ROOT%"

echo [Battleship] Root: %ROOT%

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
  if not exist "%ROOT%\desktop\node_modules" (
    echo [Battleship] Installing desktop dependencies...
    call npm --prefix "%ROOT%\desktop" ci
    if errorlevel 1 goto :fail
  )
  if not exist "%ROOT%\frontend\node_modules" (
    echo [Battleship] Installing frontend dependencies...
    call npm --prefix "%ROOT%\frontend" ci
    if errorlevel 1 goto :fail
  )

  if not exist "%ROOT%\backend\.venv\Scripts\python.exe" (
    echo [Battleship] Creating backend venv...
    py -3 -m venv "%ROOT%\backend\.venv"
    if errorlevel 1 goto :fail
  )

  echo [Battleship] Installing backend dependencies...
  call "%ROOT%\backend\.venv\Scripts\python.exe" -m pip install -e "%ROOT%\backend[dev]"
  if errorlevel 1 goto :fail

  set "BATTLESHIP_BACKEND_DIR=%ROOT%\backend"
  set "BATTLESHIP_PYTHON=%ROOT%\backend\.venv\Scripts\python.exe"

  echo [Battleship] Starting desktop dev mode...
  call npm --prefix "%ROOT%\desktop" run dev
  exit /b %errorlevel%
)

echo [Battleship] Cargo/Rust not found. Fallback to web mode.

if not exist "%ROOT%\backend\.venv\Scripts\python.exe" (
  echo [Battleship] Creating backend venv...
  py -3 -m venv "%ROOT%\backend\.venv"
  if errorlevel 1 goto :fail
)

echo [Battleship] Installing backend dependencies...
call "%ROOT%\backend\.venv\Scripts\python.exe" -m pip install -e "%ROOT%\backend[dev]"
if errorlevel 1 goto :fail

if not exist "%ROOT%\frontend\node_modules" (
  echo [Battleship] Installing frontend dependencies...
  call npm --prefix "%ROOT%\frontend" ci
  if errorlevel 1 goto :fail
)

start "Battleship Backend" cmd /k "cd /d \"%ROOT%\backend\" && .venv\Scripts\python.exe -m uvicorn app.main:app --host 127.0.0.1 --port 8000"
start "Battleship Frontend" cmd /k "cd /d \"%ROOT%\frontend\" && npm run dev"
timeout /t 3 >nul
start "" "http://localhost:5173"
exit /b 0

:fail
echo [Battleship] Startup failed.
exit /b 1
