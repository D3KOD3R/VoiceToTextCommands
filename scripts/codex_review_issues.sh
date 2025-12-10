#!/usr/bin/env bash
set -e

ISSUES_FILE=".voice/voice-issues.md"

if [ ! -f "" ]; then
  echo "No voice issues file found at "
  exit 1
fi

codex --full-auto "Use the issues in @ as your task list. For each issue you address:
1) Update the codebase accordingly.
2) Edit @ and change its checkbox from [ ] to [x], adding a short note like 'fixed in file X'.

Do not tick issues you haven't actually worked on."
