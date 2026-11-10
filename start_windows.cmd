@echo off
setlocal
cd /d "%~dp0"
if not exist ".venv\Scripts\python.exe" (
  echo Run setup_windows.ps1 first.
  exit /b 1
)
set "REELMATE_SINGLE_USER=1"
if not defined REELMATE_DATA_DIR set "REELMATE_DATA_DIR=%~dp0data"
".venv\Scripts\python.exe" -m streamlit run streamlit_reelmate.py --server.address 127.0.0.1
