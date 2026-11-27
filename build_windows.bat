@echo off
rem Double-click wrapper for packaging\build_windows.ps1
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0packaging\build_windows.ps1"
pause
