@echo off
REM ============================================================
REM  Star Card Analyzer - One-click installer (Windows)
REM  Usage: double-click this file, or run from command line
REM  After install: streamlit run app.py  (or start_app.bat)
REM ============================================================
cd /d "%~dp0.."
chcp 65001 >nul

echo ============================================================
echo   Star Card Analyzer - Installation
echo   Step 1/4: Creating virtual environment (venv)...
echo ============================================================
python -m venv venv
if errorlevel 1 (
    echo [ERROR] Failed to create venv. Please install Python 3.10+ first:
    echo         https://www.python.org/downloads/
    echo         (Check "Add python.exe to PATH" during install)
    pause
    exit /b 1
)

echo.
echo ============================================================
echo   Step 2/4: Installing dependencies (may take a few minutes)...
echo ============================================================
venv\Scripts\python -m pip install --upgrade pip
venv\Scripts\python -m pip install -r requirements.txt
if errorlevel 1 (
    echo.
    echo [TIP] If this failed due to network, try the China mirror:
    echo       venv\Scripts\python -m pip install -r requirements.txt
    echo           -i https://pypi.tuna.tsinghua.edu.cn/simple
    pause
    exit /b 1
)

echo.
echo ============================================================
echo   Step 3/4: Installing Chromium for eBay scraping (optional,
echo   only needed for data collection, not for basic evaluation)...
echo ============================================================
venv\Scripts\python -m playwright install chromium
if errorlevel 1 (
    echo [WARN] Chromium install failed - data collection will be
    echo        limited to CardHobby. Basic evaluation still works.
)

echo.
echo ============================================================
echo   Step 4/4: Preparing config files...
echo ============================================================
if not exist "agent.env" (
    copy agent.env.example agent.env >nul
    echo Created agent.env from template. Edit it to add your LLM API key
    echo (optional - the app works without it, AI chat falls back to guide mode).
)

if exist "models\xgb_card_pricing.joblib" (
    echo Pre-trained model found - ready to use.
) else (
    echo [WARN] Model not found. Run: venv\Scripts\python train.py
    echo        (requires data/*_comps_database.csv, see README)
)

echo.
echo ============================================================
echo   Installation complete!
echo.
echo   Start the app:      scripts\start_app.bat   (or: streamlit run app.py)
echo   Open in browser:    http://localhost:8501
echo   Optional AI chat:   edit agent.env, then restart
echo ============================================================
pause
