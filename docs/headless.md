# Headless unattended runs

How to run the kit with nobody at the keyboard: `claude -p` with a committed allowlist, every off-list command denied
and logged (never a hang on a prompt), a session id you can resume, a heartbeat on GitHub and a watcher that tells
you when the run ended or stalled.

## Pre-launch checklist
1. **Allowlist committed.** `.claude/settings.json` (allow/deny lists and hooks) is committed on the run branch
   **before** launch: the run cannot edit settings.json, and an off-list command is denied, not asked. Add what the
   brief needs (an engine binary, `ffmpeg`, a test runner) now.
2. **Python name.** Hook commands use `python`. On a Linux box with only `python3`, run
   `python3 tools/init_project.py ... --python python3` at init (or set the hook commands to `python3` and commit).
3. **Folder trust.** Run `claude` once interactively in the clone and accept the trust dialog, or set
   `"hasTrustDialogAccepted": true` for the project path under `projects` in `~/.claude.json`. Without it a headless
   session may ignore the project's settings and hooks.
4. **Run branch fetched and checked out** (`git fetch origin <run-branch> && git checkout <run-branch>`), clean tree.
5. **Auth:** `CLAUDE_CODE_OAUTH_TOKEN` (from `claude setup-token`) or `ANTHROPIC_API_KEY` set in the environment.
6. **Selftest:** `python tests/selftest.py` prints `SELFTEST OK` (the launcher runs it).

## Launch
```bash
tools/headless/launch.sh --branch r2-run              # Linux / macOS / Git Bash (nohup ... & for a detached run)
powershell -NoProfile -File tools/headless/launch.ps1 -Branch r2-run    # Windows
```
The launcher checks the list above, refuses while the session recorded in `.claude/run-state/session.json` is still
alive, takes the session id from `--session-id <uuid>` (`-SessionId`; validated, else a fresh uuid4), prints the resume
command and runs:
```
claude -p "<handoff line>" --permission-mode acceptEdits --session-id <id> --output-format stream-json --verbose
```
with `KIT_HEADLESS=1`, recording `.claude/run-state/session.json` (runtime file, git-ignored)
`{session_id, pid, started, branch, head, mode: "headless", log_path, stream, launcher, resumes}` (pid = the claude
process; log_path = `~/.claude/projects/<slug>/<id>.jsonl`, slug = the project path with every non-alphanumeric
character replaced by `-`). The stream goes to `build/headless/<id>.stream.jsonl`.
Pre-assign the id when something must know it before the run starts (a watcher started first, an operator note):
```bash
SID=$(python3 -c 'import uuid; print(uuid.uuid4())')
tools/headless/launch.sh --branch r2-run --session-id "$SID"    # session.json, log path, claude --session-id, resume hint
tools/watch/run_watch.sh --repo <owner>/<repo> --branch r2-run --project-dir . --session-id "$SID"
```
Never use `--permission-mode bypassPermissions` or `--dangerously-skip-permissions`: the committed allowlist plus the
guard hook is the containment (README, "What the guard is").

**Resume** after a stall, a crash, a usage limit or a brief fix (same session, same context), never as a second
live session:
```bash
tools/headless/resume.sh [--prompt "<what changed, continue>"] [--grace 20] [--force] [--dry-run]
```
It reads `session.json`; if its pid is still a live claude process of this session (the command line names the
session id) it logs that it is killing it to `.claude/run-state/resume.log` and stderr, sends TERM, waits `--grace`
seconds, then KILL. A pid that now belongs to another process is left alone; a live pid whose command line cannot be
read is neither killed nor resumed unless `--force`. Then it runs
```
claude -p --resume <id> "<prompt>" --permission-mode acceptEdits --output-format stream-json --verbose
```
with `KIT_HEADLESS=1` (stream `build/headless/<id>.resume-<n>.stream.jsonl`), records the new pid, `resumes` and
`resumed_at` in `session.json` and logs the result's permission denials like the launcher. On Windows run it from Git
Bash (or stop the old `claude` process first and resume by hand with the command above).
The run protocol records the session id in `run-state.json` (`session_id`) and the first PROGRESS.md block.

## Denied commands are skipped and logged, never block
- `.claude/hooks/permission_log.py` (PermissionRequest hook) answers every permission request of a headless session
  (`KIT_HEADLESS=1`, or `session.json` mode `headless` for this session id) with deny and the message "Not on the
  allowlist (headless run): this command was skipped and logged ... do not retry the same command", and appends
  `{ts, session_id, tool, input}` to `.claude/run-state/denied.jsonl`. Interactive sessions are untouched.
- Hook output: `{"hookSpecificOutput": {"hookEventName": "PermissionRequest", "decision": {"behavior": "deny",
  "message": "...", "interrupt": false}}}`.
- Belt and braces: after the run the launcher copies the stream-json result's `permission_denials` into
  `denied.jsonl` too (some CLI versions deny in `-p` mode without calling the hook). CLIs that have
  `--permission-prompts none` deny anything that would prompt even without the hook.
- The run protocol: never wrap, re-route or retry a denied command; log it, pick an allowlisted alternative or cut the
  item, and list it in the run report. Grow the allowlist between runs from `denied.jsonl`.

## Heartbeat (remote / PC runs)
`.claude/hooks/heartbeat.py` (PostToolUse, matcher `*`) writes `.claude/run-state/heartbeat.json`
`{ts_utc, session_id, branch, head_sha, last_tool, run_status}` at most every `heartbeat_min` minutes (kit.json,
default 10) and pushes it as a one-file commit to the heartbeat branch (`heartbeat_branch`, default
`<run branch>-heartbeat`) from a detached background process: `git hash-object`, `mktree`, `commit-tree` (parent: the
previous heartbeat commit when fetchable), `git push origin <sha>:refs/heads/<heartbeat branch>`. It never touches
the working tree, the index or the run branch, never forces, gives up after ~20 s and only logs failures
(`hooks.log.jsonl`, outcome `push_failed`); the tool call is never slowed or failed. Disable with `"heartbeat": false`.

The watcher's stall signal is **no heartbeat or session-log write for the phase's stall limit** (STALL_MIN), or in
box mode **the claude pid in session.json is dead** while the run has not ended. The limit is per phase:
`kit.json` `"stall_min": {"default": 30, "phases": {"P3": 90}}` (give render/bake phases longer), overridden by an
optional `run-state.json` `stall_min` the run may set around a long step; the phase is `run-state.json`
`current_phase`; `--stall-min` is only the fallback when neither file sets one. The hook runs after each tool call, so
one tool call longer than the limit (a long render or bake) looks like a stall unless the long-running step touches
the heartbeat: call `python .claude/hooks/heartbeat.py --beat` between render steps (at most one push a minute), or
run the render in the background and poll it.

## Watcher
`tools/watch/run_watch.sh` blocks until the run ends or stalls and prints one JSON line (exit 0 done, 2 stall,
3 blocked/halted, 4 watcher error, 5 hard cap) with the stall limit used, the claude pid and whether it is alive, and
the below-bar headline. On a stall, pick up with `tools/headless/resume.sh` (it kills a still-live session first, so
two sessions never run on one clone). Box mode (same machine) reads the session log mtimes under
`~/.claude/projects/<slug>/`; PC mode reads the heartbeat branch on GitHub. Usage and the contract:
[`tools/watch/README.md`](../tools/watch/README.md).

## One loop: launch, watch, resume, close out (`scripts/run-loop.sh`)
```bash
scripts/run-loop.sh --tmux myproj-r3 --branch r3-run [--prompt "<handoff line>"]   # detached; tmux attach -t myproj-r3
```
A thin loop over the tools above (it reimplements none of them and never calls `claude` itself):
- **Start:** no `session.json` → `launch.sh`; recorded session dead and the run not ended → `resume.sh`; recorded
  session alive → watch only. A run-state.json that already says `done`/`blocked`/`halted` is refused unless
  `--new-run` (it would end the watch at once).
- **Watch:** `run_watch.sh --mode box --project-dir .`; `--stall-min` (default 20) is the fallback when kit.json and
  run-state.json set no limit.
- **Stall:** `resume.sh` (kills a still-live session first), up to `--max-resumes` (5); then run-state.json
  `status: blocked` with `blocked_reason`. The watcher's hard cap (`--max-hours`, default 48) also blocks.
- **End:** `done` or `blocked` → waits for claude to exit (15 min, then resume.sh stops it), resumes the same session
  once with the close-out prompt (lessons-writer subagent, STATUS.md, RUN-REPORT.md, push), then `git push origin
  HEAD:<branch>`. `halted` (`.claude/HALT`, a person's stop) skips the close-out; so does `--no-closeout`.
- Log: `.claude/run-state/run-loop.log` (git-ignored). Without tmux, `--tmux` falls back to `nohup`.

## What to read afterwards
`run-state.json` (status, session_id, below-bar phases), `RUN-REPORT.md` / `run-report.json`,
`.claude/run-state/hooks.log.jsonl` (every SubagentStop call, Stop decision, guard deny), `denied.jsonl`, and the
session log at `log_path`.
