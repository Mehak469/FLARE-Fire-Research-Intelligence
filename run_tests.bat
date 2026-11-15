@echo off
set PYTHONPATH=%~dp0src;%~dp0
python -m unittest discover -s tests -t . -v
pause
