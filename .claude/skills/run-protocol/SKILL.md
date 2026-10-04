---
name: run-protocol
description: How to execute an unattended, multi-phase run from BRIEF.md and PLAN.md - art bible gate, phase loop, style slice (dress and frame before shader tuning) and look-and-fix on visual phases with per-stage review caps (below bar never halts the run), independent visual review that calibrates on the reference, scores blind and then sees the previous round, style lock, reviews with timeouts, merge/tag/release per phase, progress logging, paid-API spend, headless runs, the final run report and the close-out. Load at the start of every unattended run and after every context compaction.
---
# Run protocol (unattended)

The owner and the orchestrating bots are away. **Never ask, never wait for a reply.** Decide, log the decision in
PROGRESS.md, keep going. The Stop hook keeps you working while PLAN.md has open phases.

## 0. Start
1. Delete `.claude/HALT` if present. Read `BRIEF.md`, `CLAUDE.md`, `PLAN.md` (if any), the tail of `PROGRESS.md`,
   `run-state.json`, and the last `run-report.json` if the brief links one.
2. Work on the run branch named in the brief (create it from `main`). The run id is `kit.json` "run". The start tag
   `<run>-start` is normally made with the owner's brief commit; if it is missing, tag the current HEAD before any
   change. Never move or delete a tag.
3. **Record the session id** (the SessionStart context shows it; headless launches also write
   `.claude/run-state/session.json` with the claude pid) in `run-state.json` (`session_id`, `status: in_progress`) and
   in the first PROGRESS.md block, so the owner can resume the session (`tools/headless/resume.sh`, which stops a
   still-running session first; docs/headless.md). Keep `run-state.json` `current_phase` up to date: the watcher
   picks the phase's stall limit (`kit.json` `stall_min`) from it.
4. If there is no PLAN.md yet: write it from `templates/PLAN.md` (as filled by `init_project.py`), then run the
   **plan-critic** (section 2), apply its findings, commit. Phases: one coherent, shippable step each, with **must**
   and **stretch** lines and a testable **minimum bar**. Size them yourself; do not pad. Visual projects
   (`kit.json` `visual.required`) keep the visual order (P1 style slice: lighting stage A, then the slice assets, then
   the style lock; content after; `docs/visual-pipeline.md`) and mark every other visual phase `[visual]`.
5. **Art bible gate:** `python tools/art_gate.py` must print `ART GATE OK` (or SKIPPED for non-visual projects) before
   any build phase. On FAIL: do not build; never write the Approved line, never edit ART-BIBLE.md, `docs/refs/` or the
   kit.json "visual" block; mark open phases `[-]` ("art gate: <reason>"), log BLOCKED, write the run report
   (section 7) with the gate output.

## 1. Phase loop (one phase at a time)
1. `date` -> timestamp. Build the phase; commit as you go (small commits, clear messages).
2. Test: the project's smoke suite and any long test. New features get cheap automated checks. A test that cannot fail
   is not a test. Randomness that affects gameplay or results must be seeded and separate from cosmetic randomness;
   when a long test exists, run it twice and compare.
3. Visual phases: **look-and-fix** (`docs/visual-pipeline.md` section 3): render the fixed shot set
   (`docs/shots/shots.json`) to `docs/shots/_work/<run>/<phase>/i<N>/` (git-ignored), **open every image next to its
   refs**, write `critique.md` there (rubric scores, top 3 problems), then fix **one change at a time**: re-render the
   affected shots, keep the change only if clearly better (commit the before/after pair under
   `docs/shots/<run>/<phase>/changes/<NN>-<what>/`), otherwise revert it. Then copy the last iteration to
   `docs/shots/<run>/<phase>/final/` (with its contact sheet) and commit it: only `final/`, `changes/` and the review
   snapshots in `rounds/` are committed. That is one **round**; each round ends with a visual-reviewer review, and the
   reviewed rounds per stage (rounds with a captured verdict) are capped by `kit.json` `visual.review_caps` (stage A
   default 3, main stage default 6). Run the benchmark and `python tools/perf_gate.py --phase P<N> <bench log>`
   (performance is this automated check, not the reviewer's). A screenshot existing is not a pass, and you never pass
   your own work: only the visual-reviewer does.
4. Style slice (P1):
   - **Dress and frame before shader tuning.** Scene dressing (vegetation, props, outcrops at the reference's density)
     and the painterly/base surface come before tuning the core asset's shader; frame the hero shot on the subject
     before the lighting lock freezes the shot set. A shader stage judged in an under-dressed frame is polished
     against the wrong target (r2: six water rounds on a ~60 % bare frame; external stylization stayed 2-3). Put the
     ref and the hero side by side at the same size in round 1.
   - **Stage A** (`P1-visualA-r<N>`, max `review_caps.stage_a` reviewed rounds, default 3): light the **dressed,
     framed area** (real rocks, grass and flower clumps, the real ground material) rather than pure placeholders,
     so the reviewer judges lighting on believable surfaces; the stage scores only `visual.stage_a_items` (keep them
     to lighting/palette-type items) against `visual.stage_a_min_score`. On a pass, or when stage A reaches its cap,
     tag `<run>-lighting-lock` (the shot set is frozen from there: `art_gate.py` fails on any change) and go on.
   - **Core deliverable on a side track:** while stage A runs, prototype the core asset (e.g. the water shader, the
     hero character) on a side track (a scene or branch of its own, not in the slice shots yet), so a slow lighting
     stage never zeroes the deliverable. Its stage (the main stage, `P1-visual-r<N>`) has **its own review budget**
     (`review_caps.default` or the phase override) regardless of how stage A ended.
   - **Main stage**: bring in one asset per route through `tools/blender/cleanup_asset.py` with `--bible ART-BIBLE.md`
     (mandatory for every AI-generated asset), each checked in the slice. **Style lock** when it passes: copy the final
     shots to `docs/style_reference/`, fill the "Style lock" section of `CLAUDE.md` (reference shots labelled "new work
     must match these", canonical files, cleanup flags, never-do list), commit. Fan out to per-asset agents only after
     P1 is closed.
   - **Below bar never halts the run.** When a stage has used its cap of reviewed rounds without a pass,
     `review.py start` refuses more rounds. Stage A at its cap: go on with the main stage. When every stage is passed
     or capped: `python tools/review.py close P<N> --known-issues` closes the phase `[x] (below bar)` and records
     `status: done_below_bar`, `known_issues`, `last_scores` and the round counts in `run-state.json`; the later
     phases then run as normal. `--known-issues` is refused for a stage without a single captured verdict. Honest
     scores only: never mark a pass, never round up, never relabel a below-bar phase as passed; skip the style lock
     when P1 closed below bar (later phases match the best state reached). The same applies to every later visual
     phase.
5. Review (section 2). Fix blocking findings; fix cheap non-blocking ones; log the rest as known issues.
6. **Close the phase before starting the next:** smoke green -> PROGRESS.md block -> `python tools/review.py close
   P<N>` (it marks the phase `[x]`; it refuses a visual phase without a stored visual-reviewer pass and perf record or
   with a stored verdict that no longer matches the hash the hook logged, accepts `--known-issues` once its stages are
   at their caps, and refuses a later phase while the style slice is still open; never mark `[x]` by hand) or `[-]`
   with a reason -> update `run-state.json` -> merge to main (`git switch main && git merge --no-ff <branch> &&
   git push origin main && git switch <branch> && git push origin <branch>`) -> tag `<run>-p<N>` -> release
   (section 4).

## 2. Reviews (subagents: plan-critic, adversarial-reviewer, visual-reviewer)
- Before launching: `python tools/review.py start <id>` (id `<phase>-<area>-r<round>`). Launch in the background.
  The Stop hook holds while a review is pending (up to `review_timeout_min`), so you may idle until it reports;
  do not start the next phase meanwhile - do the current phase's docs, shots or cleanup.
- plan-critic and adversarial-reviewer: when it reports, save its final message to a file,
  `python tools/review.py done <id> --verdict-file <file>`.
- **Timeout:** a review older than `review_timeout_min` -> stop it (TaskStop), `python tools/review.py relaunch <id>`,
  relaunch once with a tighter prompt; second timeout -> `python tools/review.py unreviewed <id>` and log it.
- At most **two** review-fix rounds per area for code reviews. Big diffs: review one area at a time.
- Give the plan-critic and adversarial-reviewer: the brief path, the phase, the diff command
  (`git diff <run>-p<N-1>..HEAD -- <paths>`), how to run the tests, and what to hunt for. They must end with the JSON
  verdict (schemas/review-verdict.schema.json).
- **Every visual phase** is gated by the **visual-reviewer**. Ids: `<phase>-visualA-r<N>` (stage A) or
  `<phase>-visual-r<N>` (main stage). `review.py start` accepts only the stage's **next round** (no skipping ahead,
  no reusing a number, not while a round is pending), refuses once the stage has used its cap of reviewed rounds,
  snapshots `final/` into `docs/shots/<run>/<phase>/rounds/<id>/` and prints the **reviewer brief** (this round's
  folder and the previous round's folder; also saved as `review-brief.md` there). The previous round's top problems
  and findings, without its scores, go to `rounds/<id>/previous-round.md`, which the reviewer opens only after it has
  scored this round and written its blind scores (no anchoring on old numbers; the comparison never raises a score).
  The reviewer calibrates on the reference first (scores the ref, judges each shot's whole-frame style and density;
  a mismatch caps the style item, `kit.json` `visual.calibration`). An in-run pass on the final stage is
  provisional until the close-out's external blind score. Give the reviewer that brief verbatim plus the shot-set version and
  the stage. No code, diffs, `critique.md`, scores (yours or earlier rounds') or hints about the verdict. It compares
  every shot with the previous round and must not reverse its own earlier requests without saying why.
- **Its verdict is captured by the SubagentStop hook** into `.claude/run-state/reviews/<id>.json`, from its last
  message, its `SubagentHandback` message (background subagents end with that tool) or its last text; the agent puts
  the verdict in both. Never run `review.py done` for it and never write that folder (the guard denies it; the hook
  logs each stored file's sha256 and `close` refuses a changed one). `python tools/review.py list` shows what was
  stored; `status: invalid` (with `problems`) means the hook could not store its output: start the next round (only
  rounds with a captured verdict count against the cap). **Two rounds in a row of one stage without a captured
  verdict** (invalid or unreviewed) set `run-state.json` `status: blocked` with `blocked_reason`: stop working on the
  phase, log BLOCKED with the reason in PROGRESS.md and end the session (the Stop hook lets a blocked run end; the
  orchestrator picks up). Every hook call is logged in `.claude/run-state/hooks.log.jsonl`. Fix its top 3 problems or
  log why not.

## 3. Logging
- **PROGRESS.md is append-only.** One block per phase (format in templates/PROGRESS.md). Timestamps only from `date`
  or `git log`, never estimated. Corrections are appended, never edited in.
- **run-state.json** (schemas/run-state.schema.json) is for the bots: update at every phase close (keep `session_id`,
  `status`, `current_phase`, `updated` as ISO-8601 UTC from `date -u +%Y-%m-%dT%H:%M:%SZ`).
- **CLAUDE.md**: add every gotcha that cost a retry (one line, with the fix).

## 4. Release
Export/build, zip as `<project>-<platform>-<run>-p<N>.zip`, `gh release upload <run>-build <zip> --clobber` on one
prerelease (create once: `gh release create <run>-build --prerelease --target main`). Delete superseded zips from the
release (`gh release delete-asset`) so only the latest few remain. Never tag a name equal to a branch name.

## 5. Paid APIs
Only through `python tools/paid.py <service> [--estimate N] -- <command>` (the guard hook denies the raw binary).
Dry-run first when the service has one. Stop new jobs before the cap; log the ledger totals per phase. Generation
prompts describe style traits, never another game.

## 6. When stuck
- Past 2x the phase's estimate, or the same failure 3 times: push the work to `<branch>-wip-p<N>`, restore the code to
  the last green tag (`git checkout <run>-p<last> -- <code dirs>`), commit forward (never reset a pushed branch), mark
  the phase `[-]` with a reason, log `BLOCKED`, continue with the next phase.
- **A blocked or denied command** (permission prompt, guard, deny rule; in headless runs the PermissionRequest hook
  denies everything off the allowlist and logs it to `.claude/run-state/denied.jsonl`): never wrap or re-route it (no
  python, cmd, PowerShell or script wrapper, no other spelling of the same command) and never retry it. Stop that
  approach, log it in PROGRESS.md, report it in the run report, and pick an allowlisted alternative or cut the item.
- Long renders or bakes (> `heartbeat_min`): run `python .claude/hooks/heartbeat.py --beat` between steps so the
  watcher does not take a long tool call for a stall; render/bake phases get a longer limit in `kit.json`
  `stall_min.phases` (set by the owner), or set `run-state.json` `stall_min` (minutes) around one long step and remove
  it afterwards.
- Create `.claude/HALT` only if continuing would damage the repo or overspend.

## 7. End of run
When every phase is `[x]` or `[-]`: set `run-state.json` `status` (`done`, or `blocked`/`halted`), write
`run-report.json` (schemas/run-report.schema.json, with the run id) and `RUN-REPORT.md`: session id, usage (session
usage tool if available), wall time from git, Stop-hook continues (`.claude/run-state/continues.txt`), per-phase
reviews and outcomes, **every `done_below_bar` phase with its last scores, rounds and known issues** (from
run-state.json), spend ledger, denied/blocked commands (`.claude/run-state/denied.jsonl`, hook denies in
`hooks.log.jsonl`), known issues, and **change next time**. Then run `python tools/review.py headline`: it puts the
below-bar `headline` and `below_bar` first in `run-report.json`; start `RUN-REPORT.md` with the same headline. The
headline and the report lead with the **last stage's open issues** and, for visual runs, **the composition gap vs the
reference** (style/density, framing); never with stale stage-A problems a later stage superseded. Merge, tag,
release, push.

## 8. Close-out (after the run, same session)
The owner resumes this session (`tools/headless/resume.sh --prompt "<lessons task>"`) for the close-out
(`docs/close-out.md`): (a) asset recipe -> `docs/RECIPE.md` (general recipe + per-style presets with the starting
values that passed), (b) kit-wide pitfalls, (c) reviewer rubric fixes, (d) wasted-token report with rounds-to-pass
per stage and tokens/cost from the stream-json `modelUsage` as the baseline. Write `LESSONS.md` from
`templates/LESSONS.md` with before/after image pairs. The **external blind score is mandatory**: by default a fresh
Claude Code session (not this one) that sees only the refs, the final shots and the rubric (no run history, no
reviews, no report) scores every shot; a human or Grok Bot reviewer spot-checks its scores rather than scoring
themselves. Record it next to the in-run scores; open kit PRs for (b) and (c). The next brief starts from the recipe values and measures rounds-to-pass and tokens
against this baseline.
