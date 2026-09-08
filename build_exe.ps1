$ErrorActionPreference = 'Stop'
$projectRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $projectRoot
$python = Join-Path $env:USERPROFILE 'miniconda3\envs\safekey-build\python.exe'
if (-not (Test-Path -LiteralPath $python)) {
  Write-Error 'Missing isolated build environment: safekey-build. See README.'
  exit 1
}

& $python -m PyInstaller --noconfirm --clean --onefile --windowed --noupx --exclude-module tkinter `
  --name SafeKey_V3 `
  --distpath "$projectRoot\dist" `
  --workpath "$projectRoot\build" `
  "$projectRoot\host\safe_key_qt.py"

if ($LASTEXITCODE -ne 0) {
    Write-Error "EXE build failed with exit code: $LASTEXITCODE"
    exit $LASTEXITCODE
}

Write-Host "EXE created: $projectRoot\dist\SafeKey_V3.exe"
