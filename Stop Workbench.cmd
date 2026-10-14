@echo off
cd /d "%~dp0"
python stop.py
if errorlevel 1 pause
