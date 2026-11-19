@echo off
setlocal DisableDelayedExpansion
cd /d "%~dp0"

if exist .env (
    for /f "usebackq tokens=1,* delims==" %%a in (".env") do (
        set "%%a=%%b"
    )
)

if not exist .fs-session.json (
    echo [INFO] Aucune session France Student trouvee (.fs-session.json).
    echo        Lancez: node scripts\fs_session_login.js
    echo        puis connectez-vous une fois a la page France Student dans le navigateur.
)
if not defined FS_API_KEY (
    echo [INFO] FS_API_KEY n'est pas defini: le bridge utilise la session du navigateur.
)

set PYTHONIOENCODING=utf-8

if "%BIND_HOST%"=="" set BIND_HOST=127.0.0.1
if "%BIND_PORT%"=="" set BIND_PORT=8765

echo ========================================
echo   Bridge Service - France Student API
echo ========================================
echo.
echo Endpoints:
echo   Health:  http://%BIND_HOST%:%BIND_PORT%/health
echo   Models:  http://%BIND_HOST%:%BIND_PORT%/v1/models
echo   Chat:    http://%BIND_HOST%:%BIND_PORT%/v1/chat/completions
echo   Images:  http://%BIND_HOST%:%BIND_PORT%/v1/images/generations
echo.

python bridge_server.py
