$issuesFile = ".voice/voice-issues.md"
if (-not (Test-Path $issuesFile)) {
    Write-Host "No voice issues file found at $issuesFile"
    exit 1
}

codex --full-auto @"
Use the issues in @$issuesFile as your task list. For each issue you address:
1) Before starting, change its checkbox to [working on] so the UI shows progress.
1) Update the codebase accordingly.
2) Edit @$issuesFile and change its checkbox to [x], adding a short note like 'fixed in file X'.
3) After the user confirms the fix is acceptable, delete the resolved item from @$issuesFile (do not delete without confirmation).

Do not tick issues you haven't actually worked on.
"@
