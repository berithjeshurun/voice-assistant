# Amy product entry — always-on host + HUD server + persistent companion orb.
param(
  [switch]$Lan,
  [switch]$Console,
  [switch]$Force,
  [switch]$NoOrb,
  [string]$Bind = "127.0.0.1",
  [int]$Port = 8787
)
. "$PSScriptRoot\_env.ps1"
Write-Host "Amy voice host"
Write-Host "  HIVE_CONFIG=$env:HIVE_CONFIG"
Write-Host "  PYHIVE_HOME=$env:PYHIVE_HOME"
Write-Host "  wake: Whisper hey chloe / chloe | Ctrl+Shift+A (no Vosk)"
Write-Host "  stt: faster-whisper medium.en (GPU) — wake + conversation + barge-in"
Write-Host "  tools: auto-approve (no [y/N] confirms)"
Write-Host "  orb: Crystalized Ball (use -NoOrb to disable)"

$argsList = @("serve", "--bind", $Bind, "--port", "$Port")
if ($Lan) { $argsList += "--lan" }
if ($Console) { $argsList += "--console" }
if ($Force) { $argsList += "--force" }
if ($NoOrb) { $argsList += "--no-orb" }

python -m amy @argsList
