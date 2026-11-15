@echo off
REM Starts the FLARE dashboard in your browser.
set PYTHONPATH=%~dp0src
if not exist "%~dp0db\flame.db" python -m flare.cli build-all
python -m streamlit run "%~dp0src\flare\ui\Home.py"
