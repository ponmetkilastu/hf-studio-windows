@echo off
cd /d "%~dp0"
where python >nul 2>nul
if %errorlevel%==0 (
    python launcher.py
) else (
    py launcher.py
)
if errorlevel 1 pause
