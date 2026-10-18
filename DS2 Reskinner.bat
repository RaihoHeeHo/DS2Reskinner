@echo off
rem Double-click to start DS2 Reskinner on Windows.
cd /d "%~dp0"
where py >nul 2>nul && (py -3 ds2_reskinner.py) || (python ds2_reskinner.py)
if errorlevel 1 (
  echo.
  echo DS2 Reskinner needs Python 3 from https://www.python.org
  echo Tick "Add python.exe to PATH" when installing.
  pause
)
