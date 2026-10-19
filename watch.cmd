@echo off
rem Keeps out\bigambitions.sqlite in sync with the latest save while you play. Ctrl+C to stop.
cd /d "%~dp0"
if exist ".venv\Scripts\python.exe" (set PY=.venv\Scripts\python.exe) else (set PY=python)
%PY% sync.py --watch
pause
