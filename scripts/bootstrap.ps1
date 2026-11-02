# Install Hive arsenal (editable) + Amy product package.
. "$PSScriptRoot\_env.ps1"

$A = $env:HIVE_ARSENAL
if (-not (Test-Path $A)) { throw "Arsenal missing: $A" }

[Environment]::SetEnvironmentVariable("PYHIVE_HOME", $env:PYHIVE_HOME, "User")
[Environment]::SetEnvironmentVariable("HIVE_CONFIG", $env:HIVE_CONFIG, "User")
[Environment]::SetEnvironmentVariable("AMY_WAKE_PHRASE", "hey chloe", "User")

Write-Host "Installing libraries from $A ..."
python -m pip install `
  -e "$A\pyhive" `
  -e "$A\hivedb" `
  -e "$A\hiveworkers" `
  -e "$A\hivesteam" `
  -e "$A\hivepersona" `
  -e "$A\hivescreen" `
  -e "$A\hivepulse" `
  -e "$A\hivesense" `
  -e "$A\hivecraft" `
  -e "$A\hiveknow" `
  -e "$A\hivetrace"

python -m pip install -e "$A\pyhive[ambient]" -e "$A\pyhive[react-ui]" -e "$A\pyhive[coding]"

Write-Host "Installing Amy package ..."
python -m pip install -e "$env:AMY_ROOT"

$web = Join-Path $env:AMY_ROOT "apps\web"
if (Test-Path (Join-Path $web "package.json")) {
  Write-Host "Building web HUD ..."
  Push-Location $web
  try {
    npm install
    npm run build
  } finally {
    Pop-Location
  }
}

Write-Host ""
Write-Host "PYHIVE_HOME=$env:PYHIVE_HOME"
Write-Host "HIVE_CONFIG=$env:HIVE_CONFIG"
python -c "import amy, pyhive; print('amy', amy.__version__, 'pyhive', pyhive.__file__)"
Write-Host "Done. Run: .\scripts\run.ps1   LAN: .\scripts\run.ps1 -Lan"
