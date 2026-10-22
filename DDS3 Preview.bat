@echo off
cd /d "%~dp0"
where py >nul 2>nul
if errorlevel 1 (
  python ds2_previewer.py %*
) else (
  py -3 ds2_previewer.py %*
)
if errorlevel 1 pause
