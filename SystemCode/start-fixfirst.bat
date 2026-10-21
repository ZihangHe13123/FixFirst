@echo off
cd /d "%~dp0"
if not exist ".venv\Scripts\python.exe" (
  echo Run scripts\setup.ps1 first ^(see README.md^).
  pause
  exit /b 1
)
".venv\Scripts\python.exe" -m fixfirst serve
pause
