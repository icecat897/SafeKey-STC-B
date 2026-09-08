$ErrorActionPreference = 'Stop'
$projectRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $projectRoot
$python = 'C:\Users\wuyuke\AppData\Local\Programs\Python\Python39\python.exe'
if (-not (Test-Path -LiteralPath $python)) { $python = 'python' }

& $python -m PyInstaller --noconfirm --clean --onefile --windowed --noupx `
  --name SafeKey_V3 `
  --distpath "$projectRoot\dist" `
  --workpath "$projectRoot\build" `
  "$projectRoot\host\safe_key.py"

if ($LASTEXITCODE -ne 0) {
    Write-Error "EXE 打包失败，退出码：$LASTEXITCODE"
    exit $LASTEXITCODE
}

Write-Host "EXE 已生成：$projectRoot\dist\SafeKey_V3.exe"
