#!/usr/bin/env bash
set -e

ISSUES_FILE=".voice/voice-issues.md"

if [ ! -f "$ISSUES_FILE" ]; then
  echo "No voice issues file found at $ISSUES_FILE"
  exit 1
fi

pending_entries="$(python - <<'PY' "$ISSUES_FILE"
from pathlib import Path
import sys

path = Path(sys.argv[1])
lines = path.read_text(encoding="utf-8").splitlines()
filtered = []
for line in lines:
    stripped = line.strip()
    if not stripped.startswith(("- [", "* [")):
        continue
    state_char = stripped[3:4].lower()
    if state_char == "x":
        continue
    filtered.append(line)
print("\\n".join(filtered))
PY
)"

if [ -z "$pending_entries" ]; then
  echo "No pending or waitlist issues found in $ISSUES_FILE"
  exit 0
fi

codex --full-auto "$(cat <<EOF
Use the following pending/waitlist issues from @$ISSUES_FILE as your task list:
$pending_entries

For each issue you address:
1) Update the codebase accordingly.
2) Edit @$ISSUES_FILE and change its checkbox from [ ] to [x], adding a short note like 'fixed in file X'.
3) After the user confirms the fix is acceptable, delete the resolved item from @$ISSUES_FILE (do not delete without confirmation).

Do not tick issues you haven't actually worked on.
EOF
)"
