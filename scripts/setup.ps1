# Create .venv and install FixFirst with its development tools (Windows).
# Usage:  powershell -ExecutionPolicy Bypass -File scripts\setup.ps1 [-Python C:\Path\to\python.exe]
param([string]$Python = "")
$ErrorActionPreference = "Stop"
Set-Location (Join-Path $PSScriptRoot "..")
if ($Python) { $exe = $Python; $pre = @() }
elseif (Get-Command py -ErrorAction SilentlyContinue) { $exe = "py"; $pre = @("-3") }
else { $exe = "python"; $pre = @() }
& $exe @pre -c "import sys; assert sys.version_info >= (3, 10), 'FixFirst requires Python 3.10+'"
if ($LASTEXITCODE -ne 0) { throw "Python 3.10 or newer is required (pass -Python to choose one)" }
& $exe @pre -m venv .venv
if ($LASTEXITCODE -ne 0) { throw "Could not create .venv" }
& .\.venv\Scripts\python.exe -m pip install -e ".[dev]"
if ($LASTEXITCODE -ne 0) { throw "Installation failed" }
Write-Host "Installed. Double-click start-fixfirst.bat, or run: .venv\Scripts\fixfirst serve"
