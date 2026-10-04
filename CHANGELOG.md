# Changelog

## r2 lessons follow-up: rubric wording, pitfalls and gotchas
Rebased on the r2 close-out (calibration, `style_match`, blind `vs_previous` stay as enforced by kitlib and the hook).
- `docs/visual-pipeline.md` section 3: review order summary (score the ref, whole frame at display size first,
  `distance_to_ref` per shot, round-1 checks, external blind score); `life` must read as a direction in a still;
  wording for project-specific items (`stylization`, `foam`, `flow`, `depth_gradient`, `sky_reflection`).
- `docs/visual-pipeline.md`: look-and-fix pitfalls (side-by-side ref check before tuning, re-render the most
  sensitive shot after a shared-mapping change, isolate a term before guessing, first-iteration artefact probes, fast
  shot set); dressing before core-asset polish in the main stage.
- `schemas/review-verdict.schema.json`: optional `distance_to_ref`.
- `templates/CLAUDE.md` and `addons/godot/CLAUDE-gotchas.md`: new gotchas (chained shell/heredoc denials, git
  user.name, contact sheet, Godot dummy audio, unfiltered global sampler, unshaded whites under AgX, SSR on
  transparents).

## run-loop: one unattended loop that owns the run end to end
- New `scripts/run-loop.sh`: launch (or resume a dead recorded session, or watch a live one), watch with
  `run_watch.sh`, auto-resume a stall with `resume.sh` up to 5 times, then mark run-state.json `blocked` with a
  reason; on done or blocked it waits for claude to exit and resumes the same session once for the mandatory
  close-out (lessons-writer, STATUS.md, RUN-REPORT.md, push). `--tmux <name>` detaches (nohup fallback). Replaces the
  orchestrating bot's watch-then-resume relay. Built on the existing tools; it never calls `claude` itself.
- Refuses to launch over a run-state.json that already says done/blocked/halted unless `--new-run` (a stale status
  would end the watch at once). `halted` (`.claude/HALT`) skips the close-out.
- Selftest: run-loop syntax, resume-vs-launch decision, stale-status refusal. `.gitignore`: run-loop.log/.out.

## r2 close-out lessons (second pilot run)
In-run reviewer 19/21 shot-items at 4+, external blind score 7/21 (the pilot project's r2 `LESSONS.md`).
- **Reviewer calibration**: the visual-reviewer scores the reference image first, then judges each shot's whole
  frame (style, scene density, composition) against it at the ref's display size; a mismatch caps the style item
  (`kit.json` `visual.calibration`: `{"required": true, "cap_item": "style_match", "cap": 3}`). Verdicts carry
  `calibration` (schema updated); `kitlib.calibration_problems` rejects a missing one, a shot without a
  match/mismatch, and a mismatched shot above the cap. The brief asks for it every round.
- **New default rubric item `style_match`** (PR #4 review): "whole-frame style, density and framing vs the refs", the
  default `cap_item`. `cohesion` keeps its meaning (assets match each other): a cohesive frame can still be the wrong
  style.
- **`cap_item` must be a rubric item** (PR #4 review, required fix): `tools/review.py start` exits 2 ("START
  REFUSED") when `visual.calibration.required` is true and `cap_item` is not in the project's `visual.rubric`, and
  `kitlib.calibration_problems` reports it as an error instead of capping nothing. **Projects with their own style
  item (e.g. a rubric with `stylization`) must set `visual.calibration.cap_item` to it**, or no visual round starts.
- **Blind `vs_previous`** (kept, not dropped: it is what stopped r1's oscillation): the reviewer writes a
  `blind_scores` block covering every shot x item of its verdict before opening `previous-round.md` or earlier PNGs;
  the SubagentStop hook rejects a verdict that looked earlier, whose blind block misses any scored cell (PR #4
  review: missing cells escaped the check), or that scores above the blind block (the comparison can lower a score,
  never raise it).
- **Round-1 checks**: framing/composition vs the ref (before the lighting lock), foam/wake direction, bed and depth
  cues in near water, grazing reflection on the lowest shot first. On the main stage's final round the brief notes
  r2's ~12-cell leniency; an in-run pass is provisional until an external blind score.
- **Headline**: `review.py headline` / below-bar closes lead with the last stage's open problems and add a
  composition/style-gap line (calibration item at or below the cap, or a known issue naming framing/density); stage-A
  problems a later stage superseded no longer lead. Known issues list the main stage first.
- **Order of work**: dress the scene to the reference's density and set the painterly/base surface, and frame the
  hero shot, before shader tuning (visual-pipeline sections 4/5, run-protocol, P1 snippet, BRIEF, README).
- **Pitfalls**: `docs/visual-pipeline.md` section 5b (symptom -> cause -> fix -> detect early: style/density
  mismatch, texel-block noise, 8-bit stair-stepping, reflection speckle/shafts, grey foam, navy deep water, target
  rings, flat glassy near field, edits mid-render); short imperative versions in `templates/visual/snippets.md`
  (`visual-pitfalls`, inserted into CLAUDE.md) and `templates/CLAUDE.md`.
- **Close-out**: new `docs/close-out.md` and `templates/LESSONS.md`; run-protocol section 8, PLAN template line,
  BRIEF "recipe and baseline": resume the same session after every run for recipe, pitfalls, rubric fixes, the
  wasted-token report (stream-json `modelUsage`, rounds-to-pass) and a mandatory external blind score: by default a
  fresh Claude Code session that sees only the refs, the final shots and the rubric (no run history, no reviews), with
  a human or Grok Bot reviewer spot-checking its scores rather than scoring.
- **Software rendering is enough for look review**: Godot Forward+ on Mesa lavapipe under `xvfb-run` matches a GPU
  render (< 1/255 mean abs diff); the godot skills, `render_shots.gd` and README say so with the exact command; a GPU
  is only needed for perf and play-testing (perf gate deferred on software runs).
- **Launcher `--session-id <uuid>`** (`-SessionId`): pre-assigned, validated session id for session.json, the log
  path, `claude --session-id` and the resume hint; uuid4 otherwise.
- Selftest: calibration (missing, mismatch cap, per-shot judgement), the shipped kit.json's `cap_item` is a rubric
  item, `review.py start` refuses a bad `cap_item` and starts with a good one, a verdict under a bad `cap_item` is
  rejected, blind order, full blind coverage and never-raise, headline leads with
  the main stage + composition gap, launcher `--session-id` (dry run); a project with a deferred perf gate still
  exercises the perf checks; the previous-round scrubber test uses the project's own rubric names.

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
