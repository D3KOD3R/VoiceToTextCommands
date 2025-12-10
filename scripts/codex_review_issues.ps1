$issuesFile = ".voice/voice-issues.md"
if (-not (Test-Path $issuesFile)) {
    Write-Host "No voice issues file found at $issuesFile"
    exit 1
}

codex --full-auto @"
Use the issues in @$issuesFile as your task list. For each issue you address:
1) Update the codebase accordingly.
2) Edit @$issuesFile and change its checkbox from [ ] to [x], adding a short note like 'fixed in file X'.

Do not tick issues you haven't actually worked on.
"@
