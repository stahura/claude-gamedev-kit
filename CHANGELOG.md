# Changelog

## PR 2 review fixes
- **Review cap counts only real reviews** (blocking): `review.py start` accepts only the stage's next round
  (highest started + 1; refuses skipping ahead, reusing a number, or starting while a round is pending). The cap
  (`visual.review_caps`) counts only rounds with a captured verdict. Two rounds in a row of one stage without one
  (invalid, unreviewed, abandoned) set `run-state.json` `status: blocked` + `blocked_reason` (e.g. "visual review not
  captured for 2 consecutive rounds of the main stage of P1: P1-visual-r1 (invalid), P1-visual-r2 (unreviewed)"):
  the watcher exits 3, the Stop hook lets the session end. `close --known-issues` is refused unless the stage has at
  least one captured verdict. Closes the "start r6, close below bar" and "unreviewed round, close below bar" holes.
- **No double sessions on a stall pickup** (blocking): `launch.sh` / `launch.ps1` record the claude pid (with session
  id, start time, branch, stream) in `.claude/run-state/session.json` (now git-ignored) and refuse to launch while it
  is alive. New `tools/headless/resume.sh`: kills a still-live session (logged to `.claude/run-state/resume.log` and
  stderr; TERM, KILL after `--grace`), leaves a reused pid alone, then `claude -p --resume <id> --permission-mode
  acceptEdits ...` and records the new pid. Shared bookkeeping in `tools/headless/session.py`.
- **Per-phase stall limit**: `kit.json` `"stall_min": {"default": 30, "phases": {}}` (longer limits for render/bake
  phases), optional `run-state.json` `stall_min` override; the watcher uses the current phase's limit (`--stall-min`
  is the fallback), reports a dead recorded pid as a stall, and its JSON line adds `phase`, `stall_min`,
  `stall_min_source`, `pid`, `pid_alive`.
- **Verdict tamper check**: the SubagentStop hook logs the sha256 of each verdict file it stores to
  `hooks.log.jsonl`; `review.py close` (and the Stop hook's close check) refuses a phase whose stored visual verdicts
  are missing from the log or differ from it. README: the guard stops accidental writes to
  `.claude/run-state/reviews/*.json`, not a deliberate forge.
- **Anti-anchoring**: the reviewer brief no longer carries the previous round's scores. The previous round's top
  problems and findings (numeric scores scrubbed) go to `rounds/<id>/previous-round.md`, which the visual-reviewer
  opens only after scoring every shot of this round.
- **Below bar up front**: `review.py headline` (also run on a below-bar close when the report exists) puts `headline`
  ("BELOW BAR: ...") and `below_bar` first in `run-report.json` (schema updated); the watcher's JSON line carries
  `below_bar` and `headline`.
- Selftest: start r6 refused, unreviewed r1 + `--known-issues` refused, two failed rounds -> blocked (watcher exit 3),
  cap counts only verdicted rounds, verdict hash match + tamper, previous-round notes without scores, headline,
  stall limit / pid fields in the watcher, resume.sh / session.py.

## r1 lessons (first pilot run)
From an earlier pilot run, r1 (blocked: 8/8 stage-A rounds without a pass, 6 verdicts not captured, no water shader).
- **Verdict capture fix** (`.claude/hooks/subagent_stop.py`): the verdict is read from `last_assistant_message`, the
  last `SubagentHandback` input (`{"message": ...}`, nested inputs too), any other tool input holding a verdict, then
  the last assistant text. After a handback a block cannot be acted on, so an unstorable verdict is recorded
  `invalid` at once (`.pending` removed); the block-once path stays for subagents that did not hand back. The
  visual-reviewer puts its report + JSON verdict in the handback message and as its last text.
- **Hook log**: every SubagentStop call (stored/blocked/invalid/ignored/error, verdict source, problems), every Stop
  decision, every guard deny and every hook exception -> `.claude/run-state/hooks.log.jsonl`.
- **Per-stage review caps** (`visual.review_caps`: stage A 3, main stage 6, per-phase overrides; `visual.on_cap`):
  `review.py start` refuses a round past the cap; `review.py close P<N> --known-issues` closes a capped phase
  `[x] (below bar)` with `done_below_bar`, `known_issues`, `last_scores` and rounds in run-state.json. **Below bar
  never halts the run** (the "failed style slice stops the run" rule is gone). `visual.look_fix_max_iterations` is
  retired (read as the main-stage cap when `review_caps.default` is absent). `visual.stage_a_min_score` added.
- **Reviewer sees the previous round**: `review.py start` snapshots `final/` into `rounds/<id>/` and prints the brief
  (previous folder, scores, top problems, findings); the reviewer reports `vs_previous` and must not reverse itself.
- **Stage A on a dressed patch, core asset on a side track** with its own review budget (docs, PLAN snippet, skill).
- **Guard narrowed to real writes**: heredoc bodies and text arguments are never scanned; only redirect targets,
  tee/cp/mv/install/ln/rm/touch/truncate/dd/sed -i/find -delete operands, PowerShell writers and `cd` + write count.
- **settings.json**: dead `Write(.claude/run-state/**)` deny removed; `PostToolUse` heartbeat and `PermissionRequest`
  hooks; ffmpeg, `python3 tools/*`, `gh run`, `gh pr view` allowed. `init_project.py --python python3`.
- **Headless mode** (`docs/headless.md`, `tools/headless/launch.sh|.ps1`): `claude -p --permission-mode acceptEdits
  --session-id <id> --output-format stream-json --verbose`, session.json, resume command, denied commands skipped and
  logged to `denied.jsonl`.
- **Heartbeat** to `<run branch>-heartbeat` (git plumbing, background, never the run branch) and the **watcher**
  `tools/watch/run_watch.sh` (one JSON line: done/stall/blocked/halted/error/timeout).
- **Selftest**: works in initialised projects (template-default checks skipped, live `.pending`/run state not copied,
  generated root files handled) and runs itself in an `init --visual` copy; new coverage for all of the above.
