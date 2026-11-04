# Amy voice host env — portable defaults; override with env or .env
$ErrorActionPreference = "Stop"
$script:AmyRoot = Split-Path $PSScriptRoot -Parent

function Resolve-FirstExistingDir {
  param([string[]]$Candidates)
  foreach ($c in $Candidates) {
    if ($c -and (Test-Path -LiteralPath $c)) { return (Resolve-Path -LiteralPath $c).Path }
  }
  return $null
}

$env:AMY_ROOT = $script:AmyRoot
$env:HIVE_CONFIG = if ($env:HIVE_CONFIG) { $env:HIVE_CONFIG } else { Join-Path $script:AmyRoot "config\hive.yaml" }
$env:PYHIVE_ASSISTANT_NAME = if ($env:PYHIVE_ASSISTANT_NAME) { $env:PYHIVE_ASSISTANT_NAME } else { "Amy" }
$env:AMY_WAKE_PHRASE = if ($env:AMY_WAKE_PHRASE) { $env:AMY_WAKE_PHRASE } else { "hey chloe" }

if (-not $env:PYHIVE_HOME) {
  $homeCand = Resolve-FirstExistingDir @(
    "G:\HiveSTEAM",
    (Join-Path $env:USERPROFILE "HiveSTEAM"),
    (Join-Path $env:USERPROFILE ".pyhive")
  )
  $env:PYHIVE_HOME = if ($homeCand) { $homeCand } else { Join-Path $env:USERPROFILE ".pyhive" }
}

if (-not $env:HIVE_ARSENAL) {
  $ars = Resolve-FirstExistingDir @(
    "H:\New_VLibs\v4",
    (Join-Path $env:USERPROFILE "New_VLibs\v4"),
    (Join-Path $script:AmyRoot "..\New_VLibs\v4")
  )
  if ($ars) { $env:HIVE_ARSENAL = $ars }
}

$env:AMY_SILENCE_S = if ($env:AMY_SILENCE_S) { $env:AMY_SILENCE_S } else { "0.55" }
$env:AMY_MIC_GAIN = if ($env:AMY_MIC_GAIN) { $env:AMY_MIC_GAIN } else { "1.4" }
$env:AMY_WAKE_RMS = if ($env:AMY_WAKE_RMS) { $env:AMY_WAKE_RMS } else { "0.018" }
$env:PYHIVE_DISABLE_SKILL_INJECT = if ($env:PYHIVE_DISABLE_SKILL_INJECT) { $env:PYHIVE_DISABLE_SKILL_INJECT } else { "1" }
$env:PYHIVE_SILENCE_S = if ($env:PYHIVE_SILENCE_S) { $env:PYHIVE_SILENCE_S } else { "0.55" }
$env:PYHIVE_MIC_GAIN = if ($env:PYHIVE_MIC_GAIN) { $env:PYHIVE_MIC_GAIN } else { "1.4" }
$env:PYHIVE_ENERGY_THRESH = if ($env:PYHIVE_ENERGY_THRESH) { $env:PYHIVE_ENERGY_THRESH } else { "0.018" }
$env:VOICESTUDIO_BASE_URL = if ($env:VOICESTUDIO_BASE_URL) { $env:VOICESTUDIO_BASE_URL } else { "http://127.0.0.1:7860" }
# Production: no separate captions Chromium window unless explicitly enabled
$env:AMY_CHAT_WINDOW = if ($env:AMY_CHAT_WINDOW) { $env:AMY_CHAT_WINDOW } else { "0" }

$envFile = Join-Path $script:AmyRoot ".env"
if (Test-Path $envFile) {
  Get-Content $envFile | ForEach-Object {
    $line = $_.Trim()
    if (-not $line -or $line.StartsWith("#")) { return }
    $i = $line.IndexOf("=")
    if ($i -lt 1) { return }
    $k = $line.Substring(0, $i).Trim()
    $v = $line.Substring($i + 1).Trim()
    if ($v.StartsWith('"') -and $v.EndsWith('"')) { $v = $v.Substring(1, $v.Length - 2) }
    Set-Item -Path "Env:$k" -Value $v
  }
}

$env:AMY_STT_BACKEND = "faster_whisper"
$env:PYHIVE_STT_BACKEND = "faster_whisper"
$env:AMY_WHISPER_MODEL = if ($env:AMY_WHISPER_MODEL) { $env:AMY_WHISPER_MODEL } else { "medium.en" }
$env:PYHIVE_WHISPER_MODEL = if ($env:PYHIVE_WHISPER_MODEL) { $env:PYHIVE_WHISPER_MODEL } else { "medium.en" }
$env:HF_HUB_DISABLE_SYMLINKS_WARNING = if ($env:HF_HUB_DISABLE_SYMLINKS_WARNING) { $env:HF_HUB_DISABLE_SYMLINKS_WARNING } else { "1" }
$env:PYHIVE_HITL = "0"
$env:PYHIVE_APPROVE = "1"

if (-not (Test-Path -LiteralPath $env:PYHIVE_HOME)) {
  New-Item -ItemType Directory -Path $env:PYHIVE_HOME -Force | Out-Null
}

Set-Location $script:AmyRoot
