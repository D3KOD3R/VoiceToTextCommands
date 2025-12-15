<#
Quick installer for whisper.cpp binary + base.en model on Windows.

What it does:
- Downloads the official v1.8.2 x64 whisper.cpp binary ZIP
- Extracts it into .tools/whisper inside this repo
- Downloads ggml-base.en.bin into the same folder
- Optionally updates .voice_config.json in this repo to point to those paths

Usage:
  powershell -ExecutionPolicy Bypass -File install_whisper.ps1

Afterwards, set any remaining fields you need in .voice_config.json,
then run: python voice_hotkey_daemon.py
#>

param(
    [string]$ModelName = "ggml-base.en.bin",
    [switch]$NoConfigUpdate
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

# Resolve repo root (this script lives in repo root)
$repoRoot = Resolve-Path $PSScriptRoot
$installDir = Join-Path $repoRoot ".tools/whisper"
$binaryZipUrl = "https://github.com/ggml-org/whisper.cpp/releases/download/v1.8.2/whisper-bin-x64.zip"
$modelUrl = "https://huggingface.co/ggerganov/whisper.cpp/resolve/main/$ModelName"

Write-Host "[info] Install dir: $installDir"
New-Item -ItemType Directory -Path $installDir -Force | Out-Null

function Download-File {
    param(
        [Parameter(Mandatory=$true)][string]$Url,
        [Parameter(Mandatory=$true)][string]$Destination
    )
    Write-Host "[info] Downloading $Url"
    curl.exe -L $Url -o $Destination
}

# Download and extract whisper binary
$tmpZip = Join-Path ([IO.Path]::GetTempPath()) "whisper-bin-x64.zip"
Download-File -Url $binaryZipUrl -Destination $tmpZip

$tmpExtract = Join-Path ([IO.Path]::GetTempPath()) "whisper-bin-x64"
if (Test-Path $tmpExtract) { Remove-Item -Recurse -Force $tmpExtract }
Expand-Archive -Path $tmpZip -DestinationPath $tmpExtract -Force

$releaseDir = Join-Path $tmpExtract "Release"
if (-not (Test-Path (Join-Path $releaseDir "main.exe"))) {
    throw "main.exe not found in extracted archive ($releaseDir)."
}

Write-Host "[info] Copying whisper binaries..."
Get-ChildItem -Path $releaseDir | ForEach-Object {
    Copy-Item -Path $_.FullName -Destination $installDir -Force
}

# Download model
$modelPath = Join-Path $installDir $ModelName
if (-not (Test-Path $modelPath)) {
    Write-Host "[info] Downloading model to $modelPath"
    Download-File -Url $modelUrl -Destination $modelPath
} else {
    Write-Host "[info] Model already present at $modelPath (skipping download)"
}

$binaryPath = Join-Path $installDir "main.exe"

if (-not $NoConfigUpdate) {
    $configPath = Join-Path $repoRoot ".voice_config.json"
    Write-Host "[info] Updating $configPath"

    $config = [pscustomobject]@{}
    if (Test-Path $configPath) {
        $json = Get-Content -Path $configPath -Raw -Encoding UTF8
        $config = $json | ConvertFrom-Json
    }

    # Ensure repos is a dictionary so paths with ':' can be used as keys.
    if (-not $config.repos) { $config | Add-Member -NotePropertyName repos -NotePropertyValue @{} }
    if ($config.repos -isnot [System.Collections.IDictionary]) { $config.repos = @{} }
    if (-not $config.hotkeys) {
        $config | Add-Member -NotePropertyName hotkeys -NotePropertyValue @{ toggle = "ctrl+alt+i"; quit = "ctrl+alt+q" }
    }
    $alias = "local"
    if (-not $config.repos.Contains($alias)) {
        $config.repos[$alias] = @{
            path = "."
            issuesFile = ".voice/voice-issues.md"
        }
    }
    $config.defaultRepo = $alias
    if (-not $config.phrases) {
        $config | Add-Member -NotePropertyName phrases -NotePropertyValue @{ nextIssue = @("next issue","next point"); stop = @("end issues","stop issues") }
    }
    if (-not $config.stt) {
        $config | Add-Member -NotePropertyName stt -NotePropertyValue @{}
    }

    $config.stt.provider = "whisper_cpp"
    # Prefer whisper-cli.exe (main.exe is deprecated wrapper)
    $cliPath = Join-Path $installDir "whisper-cli.exe"
    if (Test-Path $cliPath) {
        $binaryPath = $cliPath
    }
    $binaryFileName = Split-Path $binaryPath -Leaf
    $relativeBinary = ".tools/whisper/$binaryFileName"
    $config.stt.binaryPath = $relativeBinary
    $relativeModel = ".tools/whisper/$ModelName"
    $config.stt.model = $relativeModel
    if (-not $config.stt.language) { $config.stt.language = "en" }
    if (-not $config.realtime) {
        $config | Add-Member -NotePropertyName realtime -NotePropertyValue @{ wsUrl = $null; postUrl = $null }
    }

    $config | ConvertTo-Json -Depth 6 | Set-Content -Path $configPath -Encoding UTF8
    Write-Host "[ok] Config updated."
}

Write-Host ""
Write-Host "[done] Whisper installed."
Write-Host "Binary : $binaryPath"
Write-Host "Model  : $modelPath"
if (-not $NoConfigUpdate) {
    Write-Host "Config : $configPath updated."
} else {
    Write-Host "Config : skipped (NoConfigUpdate set)."
}
Write-Host ""
Write-Host "Next: run 'python voice_hotkey_daemon.py' (or 'python voice_gui.py') and use your hotkey (default ctrl+alt+i)."
