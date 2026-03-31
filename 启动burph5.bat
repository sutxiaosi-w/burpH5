@echo off
setlocal
chcp 65001 >nul

set "ROOT_DIR=%~dp0"
set "BACKEND_DIR=%ROOT_DIR%backend"
set "FRONTEND_DIR=%ROOT_DIR%frontend"
set "APP_FILE=%ROOT_DIR%app.py"
set "RUN_DIR=%ROOT_DIR%.run"
set "APP_PID_FILE=%RUN_DIR%\app.pid"
set "APP_PORT=8765"
set "APP_HEALTH_URL=http://127.0.0.1:%APP_PORT%/api/health"
set "APP_URL=http://127.0.0.1:%APP_PORT%"
set "MAX_WAIT_SECONDS=45"
set "PYTHON_CMD="

if not exist "%RUN_DIR%" mkdir "%RUN_DIR%" >nul 2>nul

echo [burph5] Checking environment...

where py >nul 2>nul
if not errorlevel 1 (
    set "PYTHON_CMD=py -3"
)

if not defined PYTHON_CMD (
    where python >nul 2>nul
    if not errorlevel 1 (
        set "PYTHON_CMD=python"
    )
)

if not defined PYTHON_CMD (
    echo [error] Python not found in PATH.
    echo Install Python 3.12+ and make sure `python` or `py` is available.
    pause
    exit /b 1
)

if not exist "%APP_FILE%" (
    echo [error] app.py not found:
    echo %APP_FILE%
    pause
    exit /b 1
)

echo [burph5] Using Python:
echo %PYTHON_CMD%

%PYTHON_CMD% -c "import fastapi, httpx, mcp, pydantic, typer, uvicorn" >nul 2>nul
if errorlevel 1 (
    echo [error] Missing Python dependencies.
    echo Run:
    echo   cd /d "%ROOT_DIR%"
    echo   %PYTHON_CMD% -m pip install -r requirements.txt
    pause
    exit /b 1
)

if not exist "%FRONTEND_DIR%\dist\index.html" (
    echo [burph5] frontend\dist missing. Building frontend...
    pushd "%FRONTEND_DIR%"
    if not exist "node_modules" (
        echo [warn] frontend\node_modules not found. Installing...
        call npm.cmd install
        if errorlevel 1 (
            popd
            echo [error] Frontend dependency install failed.
            pause
            exit /b 1
        )
    )
    call npm.cmd run build
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
  "$command = '%PYTHON_CMD% \"%APP_FILE%\" --host 127.0.0.1 --port %APP_PORT%';" ^
  "$p = Start-Process -FilePath 'cmd.exe' -ArgumentList '/c', $command -WorkingDirectory '%ROOT_DIR%' -WindowStyle Hidden -PassThru;" ^
  "Set-Content -Path '%APP_PID_FILE%' -Value $p.Id -Encoding ascii"
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
