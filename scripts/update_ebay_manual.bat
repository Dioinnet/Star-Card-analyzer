@echo off
chcp 65001 >nul
REM ============================================================
REM  Star Card Analyzer - Manual eBay data update
REM
REM  ************************************************************
REM  *  WARNING: THIS TAKES 30-60 MINUTES                      *
REM  *  - 15 players x 7 series x 2 pages                      *
REM  *  - Keep this window open, do not close it               *
REM  *  - Keep the computer awake and online                   *
REM  *  - You can use other software while it runs             *
REM  ************************************************************
REM ============================================================

cd /d "%~dp0.."

set PYTHON=venv\Scripts\python.exe
if not exist "%PYTHON%" set PYTHON=python

echo.
echo ============================================================
echo   eBay MANUAL UPDATE
echo   Estimated time: 30-60 minutes
echo   Progress is printed below as it runs.
echo   Do NOT close this window until it finishes.
echo ============================================================
echo.

REM Manual eBay update: eBay only + retrain model
"%PYTHON%" scripts\update_all.py --ebay-only --players 15 --ebay-pages 2 --cardhobby-pages 0 --search-delay 5

echo.
echo ============================================================
echo   Done. See logs\update_*.log for details.
echo ============================================================
pause
