@echo off
echo ==========================================================
echo   Valkyrie MS9132 USB Reset Tool (Generic)
echo ==========================================================
echo.
net session >nul 2>&1
if errorlevel 1 goto NEED_ADMIN

echo [1/3] Stopping MythCool if running...
taskkill /f /im MythCool.exe >nul 2>&1

echo [2/3] Removing any stuck unknown USB devices (VID_0000)...
powershell -NoProfile -ExecutionPolicy Bypass -Command ^
  "$out = pnputil /enum-devices /connected; ^
   $ids = ($out | Select-String -Pattern 'USB\\VID_0000[^\s]+' | ForEach-Object { $_.Matches.Value }) | Select-Object -Unique; ^
   if (-not $ids) { Write-Host 'No stuck VID_0000 devices found.' } else { foreach ($id in $ids) { Write-Host ('Removing ' + $id); pnputil /remove-device $id } }"
echo.

echo [3/3] Scanning for hardware changes...
pnputil /scan-devices
echo.

echo Checking USB devices (looking for 345F or 0000):
pnputil /enum-devices /connected | findstr /i "345F VID_0000"
echo.
echo Tip: If VID_0000 persists, fully power off your PC and cut PSU power for 30s.
echo.
pause
exit /b 0

:NEED_ADMIN
echo [ERROR] Not running as Administrator!
echo Please RIGHT-CLICK fix_usb.bat and select "Run as administrator".
echo.
pause
exit /b 1