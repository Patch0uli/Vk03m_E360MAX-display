@echo off
echo ==========================================================
echo   Uninstall ValkyrieDisplayStudio Autostart
echo ==========================================================
echo.
net session >nul 2>&1
if errorlevel 1 goto NEED_ADMIN

echo Stopping and removing Scheduled Task "ValkyrieDisplayStudio"...
schtasks /end /tn "ValkyrieDisplayStudio" >nul 2>&1
schtasks /delete /tn "ValkyrieDisplayStudio" /f
echo.
echo Done! Autostart has been removed.
pause
exit /b 0

:NEED_ADMIN
echo [ERROR] Not running as Administrator!
echo Please RIGHT-CLICK uninstall_autostart.bat and select "Run as administrator".
echo.
pause
exit /b 1