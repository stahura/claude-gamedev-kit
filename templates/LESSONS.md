# LESSONS: PROJECT_NAME RUN_ID

<!-- Written in the close-out (docs/close-out.md), in the resumed run session. Every claim names its source
(reviews/*.json, rounds/, changes/, PROGRESS.md, git log, stream-json). Image paths are full-size files. -->

Run RUN_ID (branch <run-branch>, <start UTC> to <end UTC>): <one line: what was built, how each stage closed>.
In-run reviewer final: <n>/<cells> at 4+. External blind score (`docs/reviews/RUN_ID-external-blind-score.md`):
<n>/<cells>. Gap: <cells>.
External scorer (mandatory): <fresh Claude Code session that saw only the refs, the final shots and the rubric (no
run history, no reviews) | other: why>; spot-checked by <human or Grok Bot reviewer>: <cells checked, disagreements>.

## 0. Top lesson
<!-- The one thing the next run must do differently, with its before/after pair. -->

### Final scores: in-run reviewer vs external blind score
| Shot | Item | In-run | External | Delta |
|---|---|---|---|---|
| | | | | |
| **Total** | cells at 4+ | | | |

## (a) Asset recipe: what changed in docs/RECIPE.md and why
<!-- General recipe + per-style presets; validation markers (both scorers / in-run only / unvalidated); every value
that moved with the value it replaced and why. -->

## (b) Kit-wide pitfalls
<!-- One entry each: Symptom / Cause / Fix / Detect early / Pair (before -> after). -->
1. **<name>**
   - Symptom:
   - Cause:
   - Fix:
   - Detect early:
   - Pair: `<before.png>` -> `<after.png>`

## (c) Reviewer rubric fixes
<!-- Where in-run and external disagree; calibration and rubric wording that would have caught it in round 1. -->

## (d) Wasted-token report and baseline
| Metric | Value |
|---|---|
| Cost (stream-json modelUsage) | |
| Output tokens (thinking) | |
| Cache-read / cache-creation / uncached input tokens | |
| Result segments / turns | |
| Wall time / active model time | |
| Reviewer subagents (tokens, time each) | |

| Stage | From -> to (UTC) | Minutes | Share | ~Cost | Rounds | Result |
|---|---|---|---|---|---|---|
| | | | | | | |

### What did not help, and what would have skipped it
1.

### BASELINE for the next run
- Cost, output tokens, turns, wall time:
- Rounds-to-pass per stage:
- External blind score (cells at 4+) and cost per external 4+ cell:

## Major lessons with before/after pairs
| # | Lesson | Before | After |
|---|---|---|---|
| 1 | | | |

## Run-report headline lesson
<!-- What the headline said vs what it should have said (last stage's open issues, composition gap). -->

## Kit PRs
- (b) pitfalls: <PR link>
- (c) reviewer fixes: <PR link>
