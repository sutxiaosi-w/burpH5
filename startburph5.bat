@echo off
setlocal EnableExtensions

cd /d "%~dp0"
title burph5 Launcher

set "HOST=127.0.0.1"
set "PORT=8765"
set "URL=http://%HOST%:%PORT%"
set "PY_CMD="

where py >nul 2>nul
if not errorlevel 1 (
    set "PY_CMD=py -3"
) else (
    where python >nul 2>nul
    if errorlevel 1 (
        echo [ERROR] Python was not found in PATH.
        echo Please install Python 3.12+ and make sure py or python is available.
        echo.
        pause
        exit /b 1
    )
    set "PY_CMD=python"
)

if not exist "app.py" (
    echo [ERROR] app.py was not found.
    echo Please place this script in the burph5 repository root directory.
    echo.
    pause
    exit /b 1
)

if not exist "frontend\dist\index.html" (
    echo [WARN] frontend\dist\index.html was not found.
    echo The backend can still start, but the UI may be unavailable until the frontend is built.
    echo Build it with:
    echo   cd frontend
    echo   npm install
    echo   npm run build
    echo.
)

echo Starting burph5...
echo URL: %URL%
echo.

start "" "%URL%"
call %PY_CMD% app.py --host %HOST% --port %PORT%
set "EXIT_CODE=%ERRORLEVEL%"

echo.
if not "%EXIT_CODE%"=="0" (
    echo [ERROR] burph5 exited with code %EXIT_CODE%.
    echo If dependencies are missing, run:
    echo   python -m pip install -r requirements.txt
) else (
    echo burph5 has stopped.
)

echo.
pause
exit /b %EXIT_CODE%
