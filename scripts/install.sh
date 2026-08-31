#!/usr/bin/env bash
# ============================================================
#  Star Card Analyzer - One-click installer (macOS / Linux)
#  Usage: bash scripts/install.sh
#  After install: streamlit run app.py
# ============================================================
set -e
cd "$(dirname "$0")/.."

echo "============================================================"
echo "  Star Card Analyzer - Installation"
echo "  Step 1/4: Creating virtual environment (venv)..."
echo "============================================================"
if command -v python3 >/dev/null 2>&1; then
    PYTHON=python3
else
    PYTHON=python
fi
$PYTHON -m venv venv
PY=venv/bin/python

echo
echo "============================================================"
echo "  Step 2/4: Installing dependencies (may take a few minutes)..."
echo "============================================================"
$PY -m pip install --upgrade pip
$PY -m pip install -r requirements.txt
echo "[TIP] If pip failed due to network in China, retry with:"
echo "      $PY -m pip install -r requirements.txt -i https://pypi.tuna.tsinghua.edu.cn/simple"

echo
echo "============================================================"
echo "  Step 3/4: Installing Chromium for eBay scraping (optional,"
echo "  only needed for data collection, not for basic evaluation)..."
echo "============================================================"
$PY -m playwright install chromium || echo "[WARN] Chromium install failed - basic evaluation still works."

echo
echo "============================================================"
echo "  Step 4/4: Preparing config files..."
echo "============================================================"
if [ ! -f "agent.env" ]; then
    cp agent.env.example agent.env
    echo "Created agent.env from template. Edit it to add your LLM API key"
    echo "(optional - the app works without it, AI chat falls back to guide mode)."
fi

if [ -f "models/xgb_card_pricing.joblib" ]; then
    echo "Pre-trained model found - ready to use."
else
    echo "[WARN] Model not found. Run: $PY train.py"
    echo "       (requires data/*_comps_database.csv, see README)"
fi

echo
echo "============================================================"
echo "  Installation complete!"
echo
echo "  Start the app:   streamlit run app.py"
echo "  Open browser:    http://localhost:8501"
echo "  Optional AI chat: edit agent.env, then restart"
echo "============================================================"
