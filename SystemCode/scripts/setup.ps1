# Create .venv and install FixFirst with its development tools (Windows).
# Usage:  powershell -ExecutionPolicy Bypass -File scripts\setup.ps1 [-Python C:\Path\to\python.exe]
param([string]$Python = "", [switch]$Recreate)
$ErrorActionPreference = "Stop"
Set-Location (Join-Path $PSScriptRoot "..")
if ($Python) { $exe = $Python; $pre = @() }
elseif ((Test-Path .venv\Scripts\python.exe) -and -not $Recreate) { $exe = ".\.venv\Scripts\python.exe"; $pre = @() }
elseif (Get-Command py -ErrorAction SilentlyContinue) { $exe = "py"; $pre = @("-3") }
else { $exe = "python"; $pre = @() }
& $exe @pre -c "import sys; assert sys.version_info >= (3, 10), 'FixFirst requires Python 3.10+'"
if ($LASTEXITCODE -ne 0) { throw "Python 3.10 or newer is required (pass -Python to choose one)" }
$identity = "import sys,struct; print('%s.%s-%s' % (*sys.version_info[:2], struct.calcsize('P')*8))"
$requested = & $exe @pre -c $identity
if ($LASTEXITCODE -ne 0) { throw "Could not inspect the requested Python" }
if (Test-Path .venv) {
    if ($Recreate) {
        $selectedPath = & $exe @pre -c "import sys; print(sys.executable)"
        if ($LASTEXITCODE -ne 0) { throw "Could not locate the selected Python" }
        if ([IO.Path]::GetFullPath($selectedPath).StartsWith([IO.Path]::GetFullPath((Join-Path (Get-Location).Path '.venv')) + '\', [StringComparison]::OrdinalIgnoreCase)) {
            throw "For -Recreate choose a Python outside the .venv being replaced."
        }
        # Keep the old environment recoverable; never mix Python extension ABIs.
        $workspace = (Get-Location).Path
        $oldEnv = [IO.Path]::GetFullPath((Join-Path $workspace '.venv'))
        $backup = [IO.Path]::GetFullPath((Join-Path $workspace ('.venv-backup-' + [Guid]::NewGuid().ToString('N'))))
        if ([IO.Path]::GetDirectoryName($oldEnv) -ne $workspace -or [IO.Path]::GetDirectoryName($backup) -ne $workspace) { throw "Invalid environment path" }
        Move-Item -LiteralPath $oldEnv -Destination $backup
        Write-Host "Previous environment preserved at $backup"
    } else {
        if (-not (Test-Path .venv\Scripts\python.exe)) { throw "Incomplete .venv. Run setup with -Recreate to preserve it and create a new one." }
        $existing = & .\.venv\Scripts\python.exe -c $identity
        if ($LASTEXITCODE -ne 0 -or $existing -ne $requested) { throw "Existing .venv uses a different or broken Python. Use -Recreate to preserve it and rebuild." }
    }
}
if (-not (Test-Path .venv)) {
    & $exe @pre -m venv .venv
    if ($LASTEXITCODE -ne 0) { throw "Could not create .venv" }
}
& .\.venv\Scripts\python.exe -m pip install -e ".[dev]"
if ($LASTEXITCODE -ne 0) { throw "Installation failed" }
Write-Host "Installed. Double-click start-fixfirst.bat, or run: .venv\Scripts\fixfirst serve"
