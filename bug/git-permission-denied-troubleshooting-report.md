# Git “Permission denied” / `git status --porcelain=2` / submodule troubleshooting report (Windows)

> Purpose: Capture the observed errors, environment clues, and a professional-grade troubleshooting plan so a software engineer can quickly reproduce, diagnose, and fix the issue.

---

## 1) High-level summary

A Windows Git repo containing a **submodule** (`whisper.cpp`) intermittently fails (or appears to hang / produce no output) when running Git status operations—particularly the **porcelain v2** status used by tooling:

- Tooling / agent output reports:
  - `error: cannot create standard output pipe for status: Permission denied`
  - `fatal: Could not run 'git status --porcelain=2' in submodule whisper.cpp`

Separately, the repo/worktree shows **Windows ACL anomalies**, including an **orphaned SID** (“Account Unknown”) that still has permissions on at least one relevant folder.

The user also reports:
- Terminal/window crashes when running `git status --porcelain=2` in the submodule folder.
- Issues pushing to GitHub (branching confusion and/or push targeting).
- Many `LF will be replaced by CRLF` warnings on `git add -A` (not fatal, but relevant signal of Windows config).

---

## 2) Environment & context

### OS / Shell
- Windows (PowerShell shown in outputs)
- Some commands were run from:
  - `PS C:\WINDOWS\system32>`
  - `PS C:\Users\Mitch\Desktop\Repos\New_Repo2\VoiceToTextCommands\whisper.cpp>`
  - `PS C:\Users\Mitch\Desktop\Repos\CodingTools\VoiceToTextCommands>`

### Repos / paths referenced
- Main repo (one path shown):  
  `C:\Users\Mitch\Desktop\Repos\New_Repo2\VoiceToTextCommands`
- Submodule path:  
  `...\VoiceToTextCommands\whisper.cpp`
- A permissions screenshot was for another path (still relevant to ACL/SID theme):  
  `C:\Users\Mitch\Desktop\Repos\YouTubeChannels\Banner_Creator`

### Git configuration snippets observed
From `.git/config` (screenshot):
- A submodule entry exists:
  - `[submodule "whisper.cpp"]`
  - `url = https://github.com/ggerganov/whisper.cpp`
  - `active = true`

Global/system config location shown by `--show-origin`:
- `file:C:/Program Files/Git/etc/gitconfig`

### Line endings settings observed
- `core.autocrlf = true`
- `core.eol` and `core.safecrlf` were queried; no explicit values were shown as returned.

---

## 3) Observed errors / symptoms (verbatim)

### 3.1 Status failure with submodule (tool/agent output)
```
error: cannot create standard output pipe for status: Permission denied
fatal: Could not run 'git status --porcelain=2' in submodule whisper.cpp
```

Notes:
- This indicates Git attempted to run **a `git status` subcommand inside the submodule**, but failed while creating a stdout pipe to capture the output.

### 3.2 “Nothing happens” for `git status --porcelain=2` when run manually
Command executed inside submodule directory:
```
PS C:\Users\Mitch\Desktop\Repos\New_Repo2\VoiceToTextCommands\whisper.cpp> git status --porcelain=2
PS C:\Users\Mitch\Desktop\Repos\New_Repo2\VoiceToTextCommands\whisper.cpp> git status --porcelain=2
PS C:\Users\Mitch\Desktop\Repos\New_Repo2\VoiceToTextCommands\whisper.cpp>
```

Important clarification:
- **This can be normal** if the working tree is clean. Porcelain v2 prints **no output** when there are no changes.
- However, you also reported a **terminal/window crash** in some scenarios when running similar commands, so “no output” may be a mixed signal (clean repo vs crash).

### 3.3 Registry lookup for “Account Unknown” SID fails (orphaned SID)
SID referenced:
- `S-1-5-21-2986855663-217574463-491397383-1613662691`

Registry query:
```
reg query "HKLM\SOFTWARE\Microsoft\Windows NT\CurrentVersion\ProfileList\S-1-5-21-2986855663-217574463-491397383-1613662691" /v ProfileImagePath
ERROR: The system was unable to find the specified registry key or value.
```

Interpretation:
- This strongly suggests the SID corresponds to a **deleted/local account** (or a domain profile no longer present), leaving an **orphaned ACE** on some filesystem objects.

### 3.4 ACL evidence: “Account Unknown (SID …)” present on folder permissions
From “Advanced Security Settings …” screenshot:
- `Allow` entry for **Account Unknown (S-1-5-21-...)**
- Permission appears to be **Read, write & execute**
- Other principals include: `SYSTEM`, `Administrators`, and the current user.

### 3.5 CRLF warnings during add (not an error but relevant)
From `git add -A` output:
- Repeated warnings like:
  - `warning: LF will be replaced by CRLF in <file>.`
  - “The file will have its original line endings in your working directory.”

This is consistent with:
- `core.autocrlf=true` on Windows
- Not a blocker for status/pipe creation, but part of the overall Git environment picture.

### 3.6 A command typo that was corrected (for completeness)
The following failed because of a leading `$` in PowerShell:
```
$git config --show-origin --get core.autocrlf
```
Then corrected successfully:
```
git config --show-origin --get core.autocrlf
# -> file:C:/Program Files/Git/etc/gitconfig true
```

---

## 4) Why the “pipe permission denied” is unusual

The specific message:
- `cannot create standard output pipe ... Permission denied`

…is not a typical “filesystem permission denied” (like failing to read `.git/index`).  
It indicates Windows returned an **access denied** when Git tried to create an **anonymous pipe** for process output capture (CreatePipe).

That generally points to one of these categories:

1) **Process sandboxing / job object restrictions**
   - The calling environment (terminal host, agent runner, or security product) restricts pipe creation or handle inheritance.

2) **Endpoint security / antivirus / controlled folder access**
   - Some security software interferes with process spawning, handle creation, or inter-process communications.

3) **Broken/incompatible terminal/PTY layer**
   - Certain shells/PTY bridges (ConPTY/winpty/node-pty) can produce weird “pipe” errors—especially if something changed in a CLI tool update.

4) **Corrupted Git install or hooked DLL / injected security module**
   - Less common, but possible if git.exe is being instrumented.

The presence of an **orphaned SID** in ACLs is suspicious but does **not directly explain pipe creation denial**, since pipes are not file ACL governed.  
However, it can still contribute to failures if Git touches paths that inherit problematic ACLs or triggers security heuristics.

---

## 5) Working theory of what’s happening

### What Git is doing
When you run `git status` in the **superproject**, Git may:
- enumerate submodules
- run a `git status --porcelain=2` inside each submodule to determine its state
- capture the output via a pipe

The error suggests:
- Git cannot create that pipe in the current execution environment **when entering the submodule** (or when trying to capture output for that submodule).

### What you observed manually
Running `git status --porcelain=2` inside the submodule returned no output, which *could* simply mean:
- Submodule is clean  
But your report of window crashes suggests you may have multiple execution environments:
- “normal” PowerShell (works)
- “agent/terminal host” (fails / crashes)

---

## 6) Reproduction checklist for an engineer

### 6.1 Confirm in multiple terminals (important)
Run the same commands in:
- Windows Terminal PowerShell
- VS Code integrated terminal
- classic `cmd.exe`
- Git Bash

Record which ones fail vs succeed.

### 6.2 Baseline commands (superproject)
From repo root:
```powershell
cd C:\Users\Mitch\Desktop\Repos\New_Repo2\VoiceToTextCommands

git --version
where git

git status
git status --porcelain=2
git status --porcelain=2 --ignore-submodules=all
git submodule status
git submodule foreach --recursive "git status --porcelain=2"
```

Expected:
- If `--ignore-submodules=all` works but default fails, the problem is isolated to submodule enumeration.

### 6.3 Baseline commands (submodule)
```powershell
cd .\whisper.cpp
git rev-parse --is-inside-work-tree
git status --porcelain=2
git status
```

Note:
- `git status --porcelain=2` is empty if clean.
- `git status` should still show branch info even if clean.

### 6.4 Enable tracing (critical data for root cause)
From repo root:
```powershell
$env:GIT_TRACE = "1"
$env:GIT_TRACE2_EVENT = "$pwd\git-trace2.json"
$env:GIT_TRACE_PACKET = "1"
$env:GIT_TRACE_PERFORMANCE = "1"

git status --porcelain=2
git status --porcelain=2 --ignore-submodules=all
```

Attach:
- `git-trace2.json`
- console output

(If the trace file itself fails to write, that’s additional evidence of environment restrictions.)

---

## 7) Permissions & identity diagnostics (SID/ACL angle)

### 7.1 Identify where the “Account Unknown” ACE exists
Run:
```powershell
# Replace path as needed
icacls "C:\Users\Mitch\Desktop\Repos\New_Repo2\VoiceToTextCommands" /save acl_root.txt /t
icacls "C:\Users\Mitch\Desktop\Repos\New_Repo2\VoiceToTextCommands\whisper.cpp" /save acl_submodule.txt /t
```

Look for:
- orphaned SID entries
- any explicit DENY entries
- broken inheritance

### 7.2 Validate whether the SID resolves
You already observed:
- Registry profile key for the SID is missing (likely orphaned).

Optional:
```powershell
# Attempt to translate SID -> name (may fail if account deleted)
$objSID = New-Object System.Security.Principal.SecurityIdentifier("S-1-5-21-2986855663-217574463-491397383-1613662691")
$objSID.Translate([System.Security.Principal.NTAccount])
```

### 7.3 Remediation (safe/standard)
If the orphaned ACE is present on repo folders:
- remove the orphaned SID from ACLs
- re-enable inheritance where appropriate
- ensure your current user + Administrators + SYSTEM have full control

(An engineer should do this carefully to avoid breaking other permissions.)

---

## 8) Git/submodule integrity checks

From repo root:
```powershell
git submodule sync --recursive
git submodule update --init --recursive

git fsck
git -C whisper.cpp fsck
```

If submodule is in a broken state:
```powershell
# WARNING: this is destructive to local changes in the submodule
git submodule deinit -f whisper.cpp
rmdir /s /q whisper.cpp
git submodule update --init whisper.cpp
```

---

## 9) Push / branch confusion (related, but distinct)

You observed `git remote show origin` reporting:
- remote branches include `main`, `chore/voice-issue-workflow`, `feat/...`
- local branch config shows push defaults.

Key point for troubleshooting:
- This does **not** directly cause the pipe/permission error.
- But if your tooling is on `chore/*` while you expect `main`, you may think “push isn’t working” when you’re simply on a different branch.

Commands to capture branch state:
```powershell
git branch -vv
git status -sb
git log --oneline --decorate -n 20
git remote -v
```

To push current branch explicitly:
```powershell
git push -u origin HEAD
```

To push to main explicitly (only if you actually intend to update main):
```powershell
git push origin HEAD:main
```

---

## 10) Security software / Windows features to check

If the error only appears in certain terminals or when invoked via an “agent CLI”:
- Check **Windows Security → Virus & threat protection → Ransomware protection → Controlled folder access**
- Check antivirus logs/quarantine events around:
  - `git.exe`
  - the repo directory
  - the submodule directory

A professional should also check:
- Event Viewer (Security + Microsoft-Windows-Windows Defender/Operational)
- Any corporate endpoint protection modules

---

## 11) What information is still missing (ask engineer to collect)

To diagnose quickly, attach:

1) Exact Git version:
```powershell
git --version
```

2) Terminal host details:
- Windows Terminal / VS Code / cmd / Git Bash
- Whether running as admin
- Whether run inside a tool (e.g., Codex CLI, node-pty, etc.)

3) Full trace outputs (`GIT_TRACE*`) from a failing run.

4) Output of:
```powershell
git config --show-origin -l
git submodule status
icacls <repo_root> /t
```

5) Confirmation whether **only** submodule status fails:
```powershell
git status --porcelain=2 --ignore-submodules=all
```

---

## 12) Short “most likely fixes” list (ordered)

1) **Confirm porcelain v2 emptiness vs failure**
   - Run `git status` (non-porcelain) in the submodule and root.

2) **Isolate submodule**
   - If `--ignore-submodules=all` makes status work reliably, focus on submodule execution path.

3) **Try different terminal hosts**
   - If it fails only via one terminal (or via an agent runner), suspect PTY/pipe restrictions.

4) **Remove orphaned SID ACL entries + normalize permissions**
   - Especially on the repo root and submodule directories.

5) **Re-initialize the submodule**
   - `git submodule deinit/update` or reclone if needed.

6) **Check security software**
   - Controlled folder access / antivirus interference.

7) **Reinstall/repair Git for Windows**
   - If pipe creation is broadly failing across repos and terminals.

---

## Appendix A — Known “gotchas” to avoid

- `git status --porcelain=2` printing nothing can be normal on a clean tree.
- The `$git ...` command form is invalid in PowerShell; use `git ...`.
- CRLF warnings are common on Windows with `core.autocrlf=true` and are usually not fatal.

---

## Appendix B — SID involved (for reference)

- `S-1-5-21-2986855663-217574463-491397383-1613662691`
- Registry profile key missing: likely a deleted/orphaned account.
