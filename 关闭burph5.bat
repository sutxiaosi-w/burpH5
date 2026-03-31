@echo off
setlocal EnableDelayedExpansion
chcp 65001 >nul

set "ROOT_DIR=%~dp0"
set "RUN_DIR=%ROOT_DIR%.run"
set "APP_PID_FILE=%RUN_DIR%\app.pid"
set "APP_FILE=%ROOT_DIR%app.py"
set "APP_PORT=8765"
set "STOPPED_ANY=0"

echo [burph5] Stopping single-port app...

if exist "%APP_PID_FILE%" (
    set /p TARGET_PID=<"%APP_PID_FILE%"
    if not defined TARGET_PID (
        echo [info] Empty pid file for app.
    ) else (
        taskkill /PID !TARGET_PID! /T /F >nul 2>nul
        if errorlevel 1 (
            echo [info] App pid !TARGET_PID! already stopped or unavailable.
        ) else (
            echo [burph5] Stopped app pid !TARGET_PID!.
            set "STOPPED_ANY=1"
        )
    )
) else (
    echo [info] No pid file for app. Falling back to process discovery.
)

for /f "usebackq delims=" %%P in (`powershell -NoProfile -Command ^
  "$app = [regex]::Escape('%APP_FILE%');" ^
  "Get-CimInstance Win32_Process | Where-Object { $_.Name -eq 'python.exe' -and $_.CommandLine -and $_.CommandLine -match $app } | Select-Object -ExpandProperty ProcessId"`) do (
    if not "%%P"=="" (
        taskkill /PID %%P /T /F >nul 2>nul
        if not errorlevel 1 (
            echo [burph5] Stopped app.py process %%P.
            set "STOPPED_ANY=1"
        )
    )
)

for /f "usebackq delims=" %%P in (`powershell -NoProfile -Command ^
  "Get-NetTCPConnection -LocalPort %APP_PORT% -ErrorAction SilentlyContinue | Where-Object { $_.State -eq 'Listen' } | Select-Object -ExpandProperty OwningProcess -Unique"`) do (
    if not "%%P"=="" (
        taskkill /PID %%P /T /F >nul 2>nul
        if not errorlevel 1 (
            echo [burph5] Stopped port %APP_PORT% owner %%P.
            set "STOPPED_ANY=1"
        )
    )
)

del "%APP_PID_FILE%" >nul 2>nul

if "%STOPPED_ANY%"=="0" (
    echo [info] No running burph5 app process found.
)

echo.
echo [burph5] Stop complete.
