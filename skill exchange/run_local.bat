@echo off
title Skill Exchange Local Server
cd /d "%~dp0"
echo ============================================================
echo   Starting Skill Exchange Platform on Localhost...
echo   Open your browser at: http://127.0.0.1:5000
echo ============================================================
echo.
if exist .venv\Scripts\python.exe (
    .venv\Scripts\python.exe app.py
) else (
    python app.py
)
pause
