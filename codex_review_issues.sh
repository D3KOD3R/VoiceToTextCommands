#!/usr/bin/env bash
set -e

ISSUES_FILE=".voice/voice-issues.md"

if [ ! -f "$ISSUES_FILE" ]; then
  echo "No voice issues file found at $ISSUES_FILE"
  exit 1
fi

codex --full-auto "$(cat <<EOF
Use the issues in @$ISSUES_FILE as your task list. For each issue you address:
1) Update the codebase accordingly.
2) Edit @$ISSUES_FILE and change its checkbox from [ ] to [x], adding a short note like 'fixed in file X'.
3) After the user confirms the fix is acceptable, delete the resolved item from @$ISSUES_FILE (do not delete without confirmation).

Do not tick issues you haven't actually worked on.
EOF
)"
