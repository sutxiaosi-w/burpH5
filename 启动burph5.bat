@echo off
setlocal
chcp 65001 >nul

set "ROOT_DIR=%~dp0"
set "BACKEND_DIR=%ROOT_DIR%backend"
set "FRONTEND_DIR=%ROOT_DIR%frontend"
set "PYTHON_EXE=%BACKEND_DIR%\.venv\Scripts\python.exe"
set "APP_FILE=%ROOT_DIR%app.py"
set "RUN_DIR=%ROOT_DIR%.run"
set "APP_PID_FILE=%RUN_DIR%\app.pid"
set "APP_PORT=8765"
set "APP_HEALTH_URL=http://127.0.0.1:%APP_PORT%/api/health"
set "APP_URL=http://127.0.0.1:%APP_PORT%"
set "MAX_WAIT_SECONDS=45"

if not exist "%RUN_DIR%" mkdir "%RUN_DIR%" >nul 2>nul

echo [burph5] Checking environment...

if not exist "%PYTHON_EXE%" (
    echo [error] Backend virtualenv not found:
    echo %PYTHON_EXE%
    echo Create backend\.venv and install dependencies first.
    pause
    exit /b 1
)

if not exist "%APP_FILE%" (
    echo [error] app.py not found:
    echo %APP_FILE%
    pause
    exit /b 1
)

if not exist "%FRONTEND_DIR%\node_modules" (
    echo [warn] frontend\node_modules not found. Installing...
    pushd "%FRONTEND_DIR%"
    npm.cmd install
    if errorlevel 1 (
        popd
        echo [error] Frontend dependency install failed.
        pause
        exit /b 1
    )
    popd
)

if not exist "%FRONTEND_DIR%\dist\index.html" (
    echo [burph5] frontend\dist missing. Building frontend...
    pushd "%FRONTEND_DIR%"
    npm.cmd run build
    if errorlevel 1 (
        popd
        echo [error] Frontend build failed.
        pause
        exit /b 1
    )
    popd
)

echo [burph5] Clearing old pid file...
del "%APP_PID_FILE%" >nul 2>nul

echo [burph5] Starting single-port app in hidden window...
powershell -NoProfile -ExecutionPolicy Bypass -Command ^
  "$p = Start-Process -FilePath '%PYTHON_EXE%' -ArgumentList '%APP_FILE% --host 127.0.0.1 --port %APP_PORT%' -WorkingDirectory '%ROOT_DIR%' -WindowStyle Hidden -PassThru; Set-Content -Path '%APP_PID_FILE%' -Value $p.Id -Encoding ascii"
if errorlevel 1 (
    echo [error] App failed to start.
    pause
    exit /b 1
)

echo [burph5] Waiting for health check...
powershell -NoProfile -Command ^
  "$deadline=(Get-Date).AddSeconds(%MAX_WAIT_SECONDS%);" ^
  "while((Get-Date) -lt $deadline){" ^
  "  try {" ^
  "    $r=Invoke-WebRequest -Uri '%APP_HEALTH_URL%' -UseBasicParsing -TimeoutSec 2;" ^
  "    if($r.StatusCode -eq 200 -and $r.Content -match 'ok'){ exit 0 }" ^
  "  } catch {};" ^
  "  Start-Sleep -Seconds 1" ^
  "}; exit 1"
if errorlevel 1 (
    echo [warn] App did not pass health check within %MAX_WAIT_SECONDS% seconds.
) else (
    echo [burph5] App ready: %APP_URL%
    start "" "%APP_URL%"
)

echo.
echo [burph5] Single-port app started in background.
echo URL: %APP_URL%
echo Stop with the close script in this folder.
