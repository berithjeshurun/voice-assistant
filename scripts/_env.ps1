# Amy voice host env. Libraries stay on H:; runtime on G:\HiveSTEAM.
$ErrorActionPreference = "Stop"
$script:AmyRoot = Split-Path $PSScriptRoot -Parent

$env:PYHIVE_HOME = if ($env:PYHIVE_HOME) { $env:PYHIVE_HOME } else { "G:\HiveSTEAM" }
$env:HIVE_CONFIG = Join-Path $script:AmyRoot "config\hive.yaml"
$env:PYHIVE_ASSISTANT_NAME = "Amy"
$env:AMY_ROOT = $script:AmyRoot
$env:AMY_WAKE_PHRASE = "hey chloe"
$env:AMY_SILENCE_S = if ($env:AMY_SILENCE_S) { $env:AMY_SILENCE_S } else { "0.55" }
$env:AMY_MIC_GAIN = if ($env:AMY_MIC_GAIN) { $env:AMY_MIC_GAIN } else { "1.4" }
$env:AMY_WAKE_RMS = if ($env:AMY_WAKE_RMS) { $env:AMY_WAKE_RMS } else { "0.018" }
$env:PYHIVE_DISABLE_SKILL_INJECT = if ($env:PYHIVE_DISABLE_SKILL_INJECT) { $env:PYHIVE_DISABLE_SKILL_INJECT } else { "1" }
$env:PYHIVE_SILENCE_S = if ($env:PYHIVE_SILENCE_S) { $env:PYHIVE_SILENCE_S } else { "0.55" }
$env:PYHIVE_MIC_GAIN = if ($env:PYHIVE_MIC_GAIN) { $env:PYHIVE_MIC_GAIN } else { "1.4" }
$env:PYHIVE_ENERGY_THRESH = if ($env:PYHIVE_ENERGY_THRESH) { $env:PYHIVE_ENERGY_THRESH } else { "0.018" }
$env:VOICESTUDIO_BASE_URL = if ($env:VOICESTUDIO_BASE_URL) { $env:VOICESTUDIO_BASE_URL } else { "http://127.0.0.1:7860" }
$env:HIVE_ARSENAL = if ($env:HIVE_ARSENAL) { $env:HIVE_ARSENAL } else { "H:\New_VLibs\v4" }

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

# Product voice stack — always Whisper (override stale parent-shell tiny.en / vosk)
$env:AMY_STT_BACKEND = "faster_whisper"
$env:PYHIVE_STT_BACKEND = "faster_whisper"
$env:AMY_WHISPER_MODEL = "medium.en"
$env:PYHIVE_WHISPER_MODEL = "medium.en"
# Quieter faster-whisper / HuggingFace downloads on Windows (no symlink support)
$env:HF_HUB_DISABLE_SYMLINKS_WARNING = if ($env:HF_HUB_DISABLE_SYMLINKS_WARNING) { $env:HF_HUB_DISABLE_SYMLINKS_WARNING } else { "1" }
# Optional: set HF_TOKEN in .env for authenticated Hub downloads (higher rate limits)
# Never block ambient voice on stdin tool confirms
$env:PYHIVE_HITL = "0"
$env:PYHIVE_APPROVE = "1"

Set-Location $script:AmyRoot
