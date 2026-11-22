@echo off
chcp 65001 >nul
title Uncle Super App
cd /d "%~dp0"

if not exist ".venv\Scripts\python.exe" (
    echo [1/3] Creating virtual environment...
    python -m venv .venv || goto :error
)

echo [2/3] Installing requirements...
".venv\Scripts\python.exe" -m pip install -q -r requirements.txt || goto :error

echo [3/3] Migrating database...
".venv\Scripts\python.exe" manage.py migrate || goto :error

echo.
echo  Uncle Super App is running at http://127.0.0.1:8000
echo  (Ctrl+C to stop)
echo.
".venv\Scripts\python.exe" manage.py runserver 0.0.0.0:8000
goto :eof

:error
echo.
echo Something went wrong. Make sure Python 3.10+ is installed and on PATH.
pause
