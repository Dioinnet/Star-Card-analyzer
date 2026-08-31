@echo off
REM ============================================================
REM  Star Card Analyzer - Daily quick update (CardHobby only)
REM  Called by Windows Task Scheduler (schtasks) every day.
REM  eBay is NOT included here - update it manually when needed
REM  via update_ebay_manual.bat (takes 30-60 min).
REM  Logs: logs\update_*.log
REM ============================================================
cd /d "%~dp0.."
chcp 65001 >nul

set PYTHON=venv\Scripts\python.exe
if not exist "%PYTHON%" set PYTHON=python

REM Daily job: CardHobby only (fast, ~3-10 min) + retrain
"%PYTHON%" scripts\update_all.py --skip-ebay --cardhobby-pages 30
