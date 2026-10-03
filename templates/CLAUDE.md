# CLAUDE.md: PROJECT_NAME

Read this, then `BRIEF.md`, `PLAN.md` and the tail of `PROGRESS.md`. Load the `run-protocol` skill for unattended runs.

## What this is
## Commands
```
# build:
# smoke tests (prints a clear GREEN/RED):
# long test:
# screenshots + contact sheet:
<!-- kit:visual-commands -->
# release:   (see run-protocol section 4)
```

## Architecture
## Conventions
- Commit as you go on the run branch; main only gets green, reviewed phases.
- Paid APIs only via `python tools/paid.py`. Assets: record source, license and hash in a SOURCES.md next to them.
<!-- kit:visual-convention -->

<!-- kit:visual-style-lock -->

## Gotchas (each cost a retry; add new ones as they bite)
- Windows: Git Bash and Python see `/tmp` differently: put scratch scripts in the scratchpad dir, pass Windows paths.
- Windows: Git Bash heredocs containing quotes sometimes fail to parse; write the script with the Write tool, then run it.
- Windows PowerShell 5.1: `*>` and `Set-Content -Encoding utf8` write UTF-16/BOM files; read logs with a BOM-aware
  reader; edit files with the editor tools or Python, not Set-Content.
- Background subagents can hang on a permission prompt with no signal: always use `tools/review.py` timeouts.
- Background subagents end with `SubagentHandback {"message": ...}`; plain text after it is not delivered. Reviewers
  put the full report + JSON verdict in the handback message and as their last text (the hook reads both).
- The kit guard denies only real write targets in `.claude/run-state/` (redirects, cp/mv/tee/rm/sed -i...); mentioning
  the path in a heredoc, commit message or echo text is fine. Read stored verdicts with `python tools/review.py list`.
- Long renders/bakes: call `python .claude/hooks/heartbeat.py --beat` between steps, or a watcher may report a stall.
- Gameplay randomness must use its own seeded RNG; cosmetic systems (audio, particles) must not consume it.
