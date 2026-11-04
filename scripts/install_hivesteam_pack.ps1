# Install Amy as a plug-and-play pack under $PYHIVE_HOME (default G:\HiveSTEAM).
. "$PSScriptRoot\_env.ps1"

$Steam = $env:PYHIVE_HOME
if (-not $Steam) { $Steam = "G:\HiveSTEAM" }
if (-not (Test-Path -LiteralPath $Steam)) {
  New-Item -ItemType Directory -Path $Steam -Force | Out-Null
}

$Packs = Join-Path $Steam "packs"
$AmyPack = Join-Path $Packs "amy-ecosystem"
$DataAmy = Join-Path $Steam "data\amy"
New-Item -ItemType Directory -Path $Packs -Force | Out-Null
New-Item -ItemType Directory -Path $DataAmy -Force | Out-Null
New-Item -ItemType Directory -Path $AmyPack -Force | Out-Null

$AmyRoot = $env:AMY_ROOT
if (-not $AmyRoot) { $AmyRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path }
$AmyPathYaml = ($AmyRoot -replace '\\', '/')

@"
id: amy-ecosystem
name: Amy Ecosystem
description: Plug-and-play Amy companion — orb, HUD, tools, vision, updates, settings.
amy_path: $AmyPathYaml
provides:
  - orb
  - hud
  - tool_catalog
  - local_apps
  - vision
  - updates
  - settings
  - alerts
entry:
  module: amy
  serve: python -m amy serve
tools: []
"@ | Set-Content -LiteralPath (Join-Path $AmyPack "manifest.yaml") -Encoding UTF8

@"
# Amy ecosystem (HiveSTEAM pack)

Installed from: $AmyRoot

This folder registers Amy under PYHIVE_HOME. Runtime code stays in the Amy repo;
HiveSTEAM holds binaries, models, and data.

## Run
cd $AmyRoot
.\scripts\run.ps1

## Packs
App packs also load from $Packs (and Amy apps\packs).
"@ | Set-Content -LiteralPath (Join-Path $AmyPack "README.md") -Encoding UTF8

$SpSrc = Join-Path $AmyRoot "apps\packs\smartpanels"
$SpDst = Join-Path $Packs "smartpanels"
if ((Test-Path -LiteralPath $SpSrc) -and -not (Test-Path -LiteralPath $SpDst)) {
  try {
    New-Item -ItemType Junction -Path $SpDst -Target $SpSrc | Out-Null
    Write-Host "Linked smartpanels -> $SpDst"
  } catch {
    Write-Host "Could not junction smartpanels: $_"
  }
}

$cfg = @{
  amy = @{
    root = $AmyRoot
    pack = "amy-ecosystem"
    enabled = $true
  }
  pyhive_home = $Steam
} | ConvertTo-Json -Depth 5
Set-Content -LiteralPath (Join-Path $Steam "config.json") -Value $cfg -Encoding UTF8

[Environment]::SetEnvironmentVariable("PYHIVE_HOME", $Steam, "User")
[Environment]::SetEnvironmentVariable("AMY_ROOT", $AmyRoot, "User")
$env:PYHIVE_HOME = $Steam
$env:AMY_ROOT = $AmyRoot

Write-Host ""
Write-Host "Amy <-> HiveSTEAM plug-and-play ready"
Write-Host "  PYHIVE_HOME=$Steam"
Write-Host "  pack=$AmyPack"
Write-Host "  amy_root=$AmyRoot"
Write-Host "Run: cd $AmyRoot; .\scripts\run.ps1"
