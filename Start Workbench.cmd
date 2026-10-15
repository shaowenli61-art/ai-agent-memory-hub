@echo off
cd /d "%~dp0"
python -B launch.py %*
if errorlevel 1 pause
