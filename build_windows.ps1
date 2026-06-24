$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $MyInvocation.MyCommand.Path
$Python = "C:\Users\47424\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe"

if (-not (Test-Path -LiteralPath $Python)) {
  $Python = "python"
}

& $Python -m pip install -r (Join-Path $Root "requirements.txt") pyinstaller
& $Python -m PyInstaller `
  --noconfirm `
  --windowed `
  --name "KouboAgent" `
  --distpath (Join-Path $Root "dist") `
  --workpath (Join-Path $Root "build") `
  --specpath $Root `
  --hidden-import requests `
  --add-data "$Root\默认数字人形象图片.png;." `
  --add-data "$Root\scripts;scripts" `
  (Join-Path $Root "app.py")

Write-Host "Built:" (Join-Path $Root "dist\KouboAgent\KouboAgent.exe")
