$ErrorActionPreference = 'Stop'
$projectRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $projectRoot

$pythonCandidates = @()
if ($env:CONDA_PREFIX) {
  $pythonCandidates += (Join-Path $env:CONDA_PREFIX 'python.exe')
}
$pythonCandidates += (Join-Path $env:USERPROFILE 'miniconda3\envs\safekey-build\python.exe')
$pythonCandidates += (Join-Path $env:USERPROFILE 'anaconda3\envs\safekey-build\python.exe')
$python = $pythonCandidates | Where-Object { Test-Path -LiteralPath $_ } | Select-Object -First 1
if (-not $python) {
  $pythonCommand = Get-Command python -ErrorAction SilentlyContinue
  if ($pythonCommand) { $python = $pythonCommand.Source }
}
if (-not $python) {
  Write-Error 'Python was not found. Activate the safekey-build Conda environment first.'
  exit 1
}

& $python -c 'import PyInstaller, PyQt6, serial, cryptography'
if ($LASTEXITCODE -ne 0) {
  Write-Error 'Build dependencies are incomplete. Install host\requirements-build.txt first.'
  exit 1
}

$buildEnvironment = Split-Path -Parent $python
$ffiRuntime = Join-Path $buildEnvironment 'Library\bin\ffi.dll'
$buildArguments = @(
  '--noconfirm', '--clean', '--onefile', '--windowed', '--noupx',
  '--exclude-module', 'tkinter',
  '--name', 'SafeKey_V3',
  '--distpath', (Join-Path $projectRoot 'dist'),
  '--workpath', (Join-Path $projectRoot 'build')
)
if (Test-Path -LiteralPath $ffiRuntime) {
  $buildArguments += @('--add-binary', "$ffiRuntime;.")
}
$buildArguments += (Join-Path $projectRoot 'host\safe_key_qt.py')

& $python -m PyInstaller @buildArguments

if ($LASTEXITCODE -ne 0) {
    Write-Error "EXE build failed with exit code: $LASTEXITCODE"
    exit $LASTEXITCODE
}

Write-Host "EXE created: $projectRoot\dist\SafeKey_V3.exe"
