@echo off
REM ============================================================
REM  Star Card Analyzer - One-click startup
REM  Usage: double-click this file, or run from command line
REM  Access: http://localhost:8501  (LAN: http://<your-ip>:8501)
REM ============================================================
cd /d "%~dp0.."

REM Use UTF-8 for Chinese output
chcp 65001 >nul

set PYTHON=venv\Scripts\python.exe
if not exist "%PYTHON%" set PYTHON=python

echo ============================================================
echo   Star Card Analyzer - Starting web UI...
echo   Press Ctrl+C in this window to stop the service.
echo ============================================================

REM Start Streamlit, bind 0.0.0.0 so phones/tablets on LAN can access
"%PYTHON%" -m streamlit run app.py --server.address 0.0.0.0 --server.port 8501

pause
