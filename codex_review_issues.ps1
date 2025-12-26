param(
    [string]$Repo
)

$scriptRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$helper = Join-Path $scriptRoot "scripts" "resolve_voice_issues.py"
$pythonArgs = @()
if ($Repo) {
    $pythonArgs += "--repo"
    $pythonArgs += $Repo
}

$issuesFile = (& python $helper @pythonArgs).Trim()
if (-not $issuesFile) {
    Write-Host "Failed to resolve the voice issues file (check .voice_config.json)" -ForegroundColor Yellow
    exit 1
}

if (-not (Test-Path $issuesFile)) {
    Write-Host "No voice issues file found at $issuesFile"
    exit 1
}

codex --full-auto @"
Use the issues in @$issuesFile as your task list. For each issue you address:
1) Before starting, change its checkbox to [working on] so the UI shows progress.
2) Update the codebase accordingly.
3) Edit @$issuesFile and change its checkbox to [x], adding a short note like 'fixed in file X'.
4) After the user confirms the fix is acceptable, delete the resolved item from @$issuesFile (do not delete without confirmation).

Do not tick issues you haven't actually worked on.
"@
