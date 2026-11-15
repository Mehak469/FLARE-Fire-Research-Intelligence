@echo off
REM Builds db\flame.db from data\raw and data\staging, writes docs\ingest_report.md. Run once, and after adding data.
set PYTHONPATH=%~dp0src
python -m flare.cli build-all
pause
