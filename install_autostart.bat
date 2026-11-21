@echo off
setlocal enabledelayedexpansion
echo ==========================================================
echo   VK03M + SilverStone E360MAX Dual-Screen Autostart Setup
echo   (Windows Task Scheduler - Admin / Silent / No UAC)
echo ==========================================================
echo.
net session >nul 2>&1
if errorlevel 1 goto NEED_ADMIN

set "PROJECT_DIR=%~dp0"
if "%PROJECT_DIR:~-1%"=="\" set "PROJECT_DIR=%PROJECT_DIR:~0,-1%"
set "APP_PY=%PROJECT_DIR%\web_editor\app.py"
set "PYTHONW="

for /f "delims=" %%I in ('where pythonw.exe 2^>nul') do (
    echo %%I | findstr /i "WindowsApps" >nul
    if errorlevel 1 if not defined PYTHONW set "PYTHONW=%%I"
)
if not defined PYTHONW (
    for %%V in (313 312 311 310) do (
        if exist "%LOCALAPPDATA%\Programs\Python\Python%%V\pythonw.exe" if not defined PYTHONW (
            set "PYTHONW=%LOCALAPPDATA%\Programs\Python\Python%%V\pythonw.exe"
        )
    )
)
if not defined PYTHONW (
    echo [ERROR] pythonw.exe not found! Please install Python 3.10+ first.
    pause
    exit /b 1
)

echo [INFO] Using Python: %PYTHONW%
echo [INFO] Target User:  %USERNAME%
echo.

echo [0/2] Stopping any previous instance...
schtasks /end /tn "ValkyrieDisplayStudio" >nul 2>&1
timeout /t 1 /nobreak >nul

echo [1/2] Registering Windows Scheduled Task "ValkyrieDisplayStudio"...
powershell -NoProfile -ExecutionPolicy Bypass -Command ^
  "$action = New-ScheduledTaskAction -Execute '%PYTHONW%' -Argument '\"%APP_PY%\"' -WorkingDirectory '%PROJECT_DIR%'; ^
   $trigger = New-ScheduledTaskTrigger -AtLogOn -User '%USERNAME%'; ^
   $principal = New-ScheduledTaskPrincipal -UserId '%USERNAME%' -LogonType Interactive -RunLevel Highest; ^
   $settings = New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries -ExecutionTimeLimit ([TimeSpan]::Zero) -RestartCount 3 -RestartInterval (New-TimeSpan -Minutes 1); ^
   Register-ScheduledTask -TaskName 'ValkyrieDisplayStudio' -Action $action -Trigger $trigger -Principal $principal -Settings $settings -Force | Out-Null"

if errorlevel 1 (
    echo [ERROR] Failed to register Scheduled Task!
    pause
    exit /b 1
)

echo [2/2] Starting ValkyrieDisplayStudio now (with Admin privileges)...
schtasks /run /tn "ValkyrieDisplayStudio"
echo.
echo ==========================================================
echo   SUCCESS! Dual-Screen Studio is now running in background
echo   with Admin privileges (CPU Temp + Watts unlocked!)
echo   Web UI: http://localhost:5050
echo   Log:    %PROJECT_DIR%\web_editor\studio.log
echo ==========================================================
echo.
pause
exit /b 0

:NEED_ADMIN
echo [ERROR] Not running as Administrator!
echo Please RIGHT-CLICK install_autostart.bat and select "Run as administrator".
echo.
pause
exit /b 1