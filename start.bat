@echo off
REM Nobeles Feedback — Lokaler Start
cd /d "%~dp0"
echo Starte Nobeles Feedback...
echo Login:  http://localhost:5000
echo Strg+C zum Beenden
echo.
"%~dp0venv\Scripts\python.exe" "%~dp0app.py"
pause
