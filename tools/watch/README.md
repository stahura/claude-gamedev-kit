# run_watch.sh: wait for an unattended run to end or stall

Blocks (polling) until the run ends, stalls or hits the hard cap, then prints **exactly one JSON line** on stdout.
Needs bash, coreutils, python3 (JSON and dates) and `gh` (or `curl` with `GH_TOKEN`/`GITHUB_TOKEN`) for GitHub.
Progress and diagnostics go to stderr only.

```bash
tools/watch/run_watch.sh --repo <owner>/<repo> --branch <run-branch> [--mode box|pc] [--session-id <id>] \
    [--project-dir <local clone>] [--log <session jsonl>] [--heartbeat-branch <b>] \
    [--interval-sec 300] [--stall-min 30] [--max-hours 6] [--once] [--offline]

# box: the run is on this machine
nohup tools/watch/run_watch.sh --repo <owner>/<repo> --branch r2-run --project-dir ~/<project> > watch.out 2> watch.log &
# pc: the run is on another machine; read its heartbeat branch on GitHub
tools/watch/run_watch.sh --repo <owner>/<repo> --branch r2-run --mode pc
```

Final line:
```json
{"repo":"<owner>/<repo>","branch":"r2-run","session_id":"...","reason":"done","last_log_write":"2026-10-03T21:11:35Z","head_sha":"...","phase":"P3","stall_min":90,"stall_min_source":"kit.json stall_min.phases.P3","pid":41233,"pid_alive":false,"below_bar":["P1"],"headline":"BELOW BAR: 1 visual phase(s) closed without a reviewer pass: P1 (main 6/6): ...","detail":"run-state.json status done (GitHub r2-run)"}
```
- `phase` / `stall_min` / `stall_min_source`: the current phase (run-state.json `current_phase`) and the stall limit
  used for it: run-state.json `stall_min`, else kit.json `stall_min.phases.<phase>`, else `stall_min.default`, else
  `--stall-min`.
- `pid` / `pid_alive`: the claude pid from `.claude/run-state/session.json` (written by `tools/headless/launch.sh`
  and `resume.sh`) and whether it is running; `null` in PC mode or without a session.json.
- `below_bar` / `headline`: phases closed below bar (run-state.json `done_below_bar`, run-report.json `below_bar`)
  and the report's `headline` (or one built from the phase list); `[]` / `null` when none. Read it first.

| reason | exit | when |
|---|---|---|
| `done` | 0 | run-state.json `status` done, or a run report of this run on the branch (outcome done/partial or none) |
| `stall` | 2 | now - `last_log_write` >= the phase's stall limit, or (box) the session.json claude pid is dead while the run has not ended |
| `blocked` / `halted` | 3 | run-state.json `status` blocked/halted (the kit sets blocked, with `blocked_reason`, when a visual stage has 2 rounds in a row without a captured verdict), a report with that outcome, or `.claude/HALT` in the local clone |
| `error` | 4 | invalid arguments, or the repo/branch not found on 3 consecutive polls (transient gh/curl failures are retried) |
| `timeout` | 5 | `--max-hours` (default 6) reached |
| `running` | 1 | `--once` only: one poll, nothing ended or stalled |

- **Run end** is read from the local clone (`--project-dir`, box mode) and from GitHub
  (`gh api repos/<repo>/contents/<file>?ref=<branch>`): `run-state.json` `status`, `run-report.json`
  (`outcome`/`status`/`result`), `RUN-REPORT.md`. A report whose run id differs from run-state.json's (a previous
  run's report still on the branch) is ignored.
- **Stall** uses the Claude session log's last write, not commits. Box mode: newest mtime of
  `~/.claude/projects/<slug>/<session>.jsonl` and `<session>/subagents/*.jsonl` (slug = the project path with every
  non-alphanumeric character replaced by `-`; session = `--session-id`, else `.claude/run-state/session.json`, else
  the newest jsonl there; `--log` names the file directly). PC mode: `ts_utc` of `heartbeat.json` on
  `<branch>-heartbeat` (written by `.claude/hooks/heartbeat.py`), else run-state.json `heartbeat`/`updated` on the run
  branch, else the head commit date (named in `detail`). With no log at all, the watcher's start time is the baseline.
  A single tool call longer than the stall limit (a long render) looks like a stall unless it beats the heartbeat
  (`python .claude/hooks/heartbeat.py --beat`); give render/bake phases a longer limit in kit.json `stall_min.phases`.
- **Picking up a stall:** run `tools/headless/resume.sh [--prompt "..."]` in the clone. It reads session.json, kills
  the old claude process if it is still alive (logged to `.claude/run-state/resume.log` and stderr; TERM, then KILL
  after `--grace` seconds), then `claude -p --resume <id> ... --permission-mode acceptEdits` and records the new pid.
  Never start a second `claude -p` on the same clone by hand (docs/headless.md).
- **Wake:** with `WAKE_URL` set, the same JSON is POSTed there (Content-Type application/json; `WAKE_AUTH` is sent as
  a full header line when it contains a colon, e.g. `Authorization: Bearer x`, else as the Authorization value),
  curl timeout 15 s, failures on stderr only. Secrets are never logged (only the URL host).
- `--offline` skips GitHub (box mode, tests). Safe under `set -u`, `nohup ... &`; it never kills other processes.
