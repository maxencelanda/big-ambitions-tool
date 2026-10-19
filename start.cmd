@echo off
rem Launches Big Ambitions Analytics (http://127.0.0.1:8765). Builds the UI on first run.
cd /d "%~dp0"
if not exist ".venv\Scripts\python.exe" (
  echo Creating the Python environment...
  python -m venv .venv && .venv\Scripts\python -m pip install -q -r requirements.txt
)
if not exist "out\gamedata\items.json" (
  echo Extracting game data...
  .venv\Scripts\python extract_gamedata.py
)
if not exist "web\dist\index.html" (
  echo Building the interface...
  pushd web && call npm install --no-audit --no-fund && call npm run build && popd
)
.venv\Scripts\python app.py
pause
