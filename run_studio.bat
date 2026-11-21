@echo off
setlocal enabledelayedexpansion
title VK03M + SilverStone E360MAX Dual Display Studio
cd /d "%~dp0"
set "PYTHON="

for /f "delims=" %%I in ('where python.exe 2^>nul') do (
    echo %%I | findstr /i "WindowsApps" >nul
    if errorlevel 1 if not defined PYTHON set "PYTHON=%%I"
)
if not defined PYTHON (
    for %%V in (313 312 311 310) do (
        if exist "%LOCALAPPDATA%\Programs\Python\Python%%V\python.exe" if not defined PYTHON (
            set "PYTHON=%LOCALAPPDATA%\Programs\Python\Python%%V\python.exe"
        )
    )
)
if not defined PYTHON (
    echo [ERROR] python.exe not found! Please install Python 3.10+ first.
    pause
    exit /b 1
)

echo ==========================================================
echo   Starting Dual Display Studio...
echo   Python: %PYTHON%
echo   Web UI: http://localhost:5050
echo ==========================================================
start "" http://localhost:5050
"%PYTHON%" web_editor\app.py
pause