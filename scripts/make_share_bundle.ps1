# Build a clean shareable Amy + Hive arsenal (v4) + HiveSTEAM zip.
# Output defaults to Desktop. No secrets / no local venvs / no rust target / no node_modules.
$ErrorActionPreference = "Stop"

. "$PSScriptRoot\_env.ps1"

$Amy = $env:AMY_ROOT
$Arsenal = $env:HIVE_ARSENAL
$Steam = $env:PYHIVE_HOME
$Stamp = Get-Date -Format "yyyyMMdd-HHmm"
$StageRoot = Join-Path $env:TEMP "AmyPlatformShare-$Stamp"
$OutZip = Join-Path ([Environment]::GetFolderPath("Desktop")) "Amy-Platform-Share-$Stamp.zip"

if (-not (Test-Path -LiteralPath $Amy)) { throw "AMY_ROOT missing: $Amy" }
if (-not (Test-Path -LiteralPath $Arsenal)) { throw "HIVE_ARSENAL missing: $Arsenal" }
if (-not (Test-Path -LiteralPath $Steam)) { throw "PYHIVE_HOME / HiveSTEAM missing: $Steam" }

Write-Host "Staging -> $StageRoot"
if (Test-Path $StageRoot) { Remove-Item -LiteralPath $StageRoot -Recurse -Force }
New-Item -ItemType Directory -Path $StageRoot | Out-Null

function Copy-Clean {
  param(
    [string]$Src,
    [string]$Dst,
    [string[]]$ExcludeDirs = @(),
    [string[]]$ExcludeFiles = @()
  )
  New-Item -ItemType Directory -Path $Dst -Force | Out-Null
  $xd = @(".git", "__pycache__", ".pytest_cache", ".mypy_cache", "node_modules", ".venv", "venv", "target") + $ExcludeDirs
  $xf = @(".env", "*.pyc", "Thumbs.db", "desktop.ini") + $ExcludeFiles
  $args = @($Src, $Dst, "/E", "/NFL", "/NDL", "/NJH", "/NJS", "/nc", "/ns", "/np", "/R:1", "/W:1")
  foreach ($d in $xd) { $args += "/XD"; $args += $d }
  foreach ($f in $xf) { $args += "/XF"; $args += $f }
  & robocopy @args | Out-Null
  $code = $LASTEXITCODE
  # robocopy: 0-7 success-ish
  if ($code -ge 8) { throw "robocopy failed ($code): $Src -> $Dst" }
}

Write-Host "Copying Amy (source + HUD dist; no node_modules / orb target / secrets)…"
Copy-Clean -Src $Amy -Dst (Join-Path $StageRoot "Amy") -ExcludeDirs @(
  ".ignore-commit", "amy.egg-info", ".cursor", "agent-transcripts"
) -ExcludeFiles @(".env")

# Drop any secrets trees that snuck in
Get-ChildItem -LiteralPath (Join-Path $StageRoot "Amy") -Recurse -Directory -Filter "secrets" -ErrorAction SilentlyContinue |
  ForEach-Object { Remove-Item $_.FullName -Recurse -Force -ErrorAction SilentlyContinue }

Write-Host "Copying Hive arsenal v4…"
Copy-Clean -Src $Arsenal -Dst (Join-Path $StageRoot "New_VLibs\v4") -ExcludeDirs @(
  ".raw", ".temp", ".ruff_cache", "dist", "build", "*.egg-info"
)

Write-Host "Copying HiveSTEAM (models + deck; no venv / logs / personal memory)…"
Copy-Clean -Src $Steam -Dst (Join-Path $StageRoot "HiveSTEAM") -ExcludeDirs @(
  "logs", "sessions", "telemetry", "env",
  "memory", "speakers", "presence", "life", "vectors", "cache", "idle", "sync"
)

# Portable path helper + share notes
$shareMd = @"
# Amy Platform Share Bundle

Layout inside this zip:

``````
Amy/                 product host + HUD
New_VLibs/v4/        Hive arsenal (bootstrap libraries)
HiveSTEAM/           runtime deck (persona, wake, VCE models, packs)
setup-paths.ps1      sets portable env vars for this machine
``````

## Cleaned out (on purpose)

- `.env` / secrets
- `node_modules`, Rust `target`, Python venvs (`HiveSTEAM/runtime/env`)
- `.git`, caches, logs, sessions
- Personal HiveSTEAM memory / speakers / vectors

## Recipient setup (Windows)

1. Unzip to a path **without spaces if possible**, e.g. ``C:\AmyPlatform``.
2. Install **Python 3.11+** and **Node.js 20+**.
3. In PowerShell:

``````powershell
cd C:\AmyPlatform
.\setup-paths.ps1
cd Amy
.\scripts\bootstrap.ps1
.\scripts\run.ps1
``````

4. Edit ``Amy\config\hive.yaml`` for **their** model endpoint (Ollama / etc.).
5. Put API keys via Amy HUD **Settings → Integrations** (never commit secrets).

Wake phrase default: **hey chloe**.

## Notes

- First bootstrap reinstalls editable Hive packages from ``New_VLibs\v4`` and rebuilds the web HUD.
- HiveSTEAM VCE / model binaries are included under ``HiveSTEAM\binaries`` (large).
- Optional Bevy orb source is included without the compiled ``target`` folder.
"@

Set-Content -LiteralPath (Join-Path $StageRoot "SHARE.md") -Value $shareMd -Encoding UTF8

$setup = @'
# Portable env for this unzipped bundle (run from bundle root).
$ErrorActionPreference = "Stop"
$Root = $PSScriptRoot
$env:AMY_ROOT = Join-Path $Root "Amy"
$env:HIVE_ARSENAL = Join-Path $Root "New_VLibs\v4"
$env:PYHIVE_HOME = Join-Path $Root "HiveSTEAM"
$env:HIVE_CONFIG = Join-Path $env:AMY_ROOT "config\hive.yaml"
$env:PYHIVE_ASSISTANT_NAME = "Amy"
$env:AMY_WAKE_PHRASE = "hey chloe"

[Environment]::SetEnvironmentVariable("AMY_ROOT", $env:AMY_ROOT, "User")
[Environment]::SetEnvironmentVariable("HIVE_ARSENAL", $env:HIVE_ARSENAL, "User")
[Environment]::SetEnvironmentVariable("PYHIVE_HOME", $env:PYHIVE_HOME, "User")
[Environment]::SetEnvironmentVariable("HIVE_CONFIG", $env:HIVE_CONFIG, "User")

# Also write Amy/.env for scripts\_env.ps1
$dotenv = @"
AMY_ROOT=$($env:AMY_ROOT)
HIVE_ARSENAL=$($env:HIVE_ARSENAL)
PYHIVE_HOME=$($env:PYHIVE_HOME)
HIVE_CONFIG=$($env:HIVE_CONFIG)
PYHIVE_ASSISTANT_NAME=Amy
AMY_WAKE_PHRASE=hey chloe
"@
Set-Content -LiteralPath (Join-Path $env:AMY_ROOT ".env") -Value $dotenv -Encoding UTF8

Write-Host "AMY_ROOT=$($env:AMY_ROOT)"
Write-Host "HIVE_ARSENAL=$($env:HIVE_ARSENAL)"
Write-Host "PYHIVE_HOME=$($env:PYHIVE_HOME)"
Write-Host "Wrote Amy\.env and User env vars. Next: cd Amy; .\scripts\bootstrap.ps1"
'@
Set-Content -LiteralPath (Join-Path $StageRoot "setup-paths.ps1") -Value $setup -Encoding UTF8

Write-Host "Compressing -> $OutZip (this can take a while; HiveSTEAM models are large)…"
if (Test-Path $OutZip) { Remove-Item -LiteralPath $OutZip -Force }

$seven = Get-Command 7z -ErrorAction SilentlyContinue
if ($seven) {
  & 7z a -tzip -mx=3 -mmt=on $OutZip (Join-Path $StageRoot "*") | Write-Host
} else {
  tar -caf $OutZip -C $StageRoot .
}

Write-Host "Removing stage…"
Remove-Item -LiteralPath $StageRoot -Recurse -Force

$item = Get-Item -LiteralPath $OutZip
Write-Host ""
Write-Host "DONE"
Write-Host ("Zip: {0}" -f $item.FullName)
Write-Host ("Size: {0:N2} GB" -f ($item.Length / 1GB))
