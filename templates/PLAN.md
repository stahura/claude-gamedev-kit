# PLAN.md: PROJECT_NAME, run RUN_ID

<!-- Written by Claude from BRIEF.md, critiqued by plan-critic before any code. -->

## Goal (from the brief, condensed)

## Run rules (re-read after every compaction; the SessionStart hook re-injects this section)
1. Never ask, never wait. Decide, log the decision in PROGRESS.md, continue.
2. One phase at a time. **Close a phase (smoke green, PROGRESS block, `python tools/review.py close P<N>` marks it
   `[x]`, run-state.json, merge to main, tag `RUN_ID-p<N>`, release) before starting the next.**
3. Reviews per phase (adversarial-reviewer). `tools/review.py start` before, `done` after. Timeout
   `review_timeout_min`: stop, relaunch once, then log unreviewed. Max two review-fix rounds per area.
4. Timestamps only from `date` or git. PROGRESS.md is append-only. The session id goes into run-state.json
   (`session_id`) and the first PROGRESS.md block at the start of the run.
5. Paid APIs only via `tools/paid.py`; caps in kit.json; stop new jobs before the cap.
6. Tests: smoke suite under its budget; long runs outside it; seeded, deterministic gameplay randomness (long test run
   twice must match).
7. Never force-push, never reset a pushed branch, never tag a branch name, never move or delete a tag. Do not edit
   `.claude/` (settings, hooks, agents, run-state).
8. CLAUDE.md gets every gotcha that cost a retry.
9. Never wrap or re-route a blocked or denied command (no python, cmd, PowerShell or script wrapper around it, no
   other spelling of it) and do not retry it: stop that approach, log it in PROGRESS.md and report it in the run
   report. Headless runs deny anything off the allowlist and log it in `.claude/run-state/denied.jsonl`.
<!-- kit:visual-rule -->
- After the run: the owner resumes this same session for the close-out (`docs/close-out.md`): LESSONS.md, recipe,
  pitfalls, reviewer fixes, the wasted-token report and baseline. The run report leads with the last stage's open
  issues, never stale earlier-stage ones.

## When stuck
Past 2x the phase estimate or the same failure 3 times: push to `<branch>-wip-p<N>`, restore code from the last green
tag, commit forward, mark the phase `[-]` with a reason, log BLOCKED, continue.

## Phases
Legend: `[ ]` open, `[x]` done (minimum bar met, tested, reviewed, merged, tagged, released), `[-]` skipped/blocked.
<!-- kit:visual-gate -->

- [ ] **P0: Foundation**
  - (must) ...
<!-- kit:visual-p0 -->
  - (stretch) ...
  - Minimum bar: ...
<!-- kit:visual-p1 -->
- [ ] **P1: ...**

## Definition of done (from the brief)
