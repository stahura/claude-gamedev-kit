# Close-out (after every run)

A run is not finished when the run report is written. The close-out turns what the run learned into reusable values
and kit fixes, and sets the baseline the next run is measured against. It runs in the **same Claude session** (it
still has the context: why each value moved, which renders were wasted), resumed by the owner once the run has ended:

```bash
tools/headless/resume.sh --prompt "Close-out for run <run>: follow docs/close-out.md; write LESSONS.md from templates/LESSONS.md"
```
(`resume.sh` stops a still-live session first; never two sessions on one clone. docs/headless.md.)

## The lessons task
1. **(a) Asset recipe** -> `docs/RECIPE.md`: a general recipe (order of work, mesh/UV contract, the layers, sampling,
   a pitfalls checklist) plus **per-style presets** (e.g. stylized/painterly, toon/flat, realistic) with the starting
   values that passed and, for every value that moved, the value it replaced and why. Mark each value by who confirmed
   it: both scorers 4+, in-run only (contested), or unvalidated.
2. **(b) Kit-wide pitfalls**: symptom -> cause -> fix -> how to detect early, each with a before/after pair where one
   exists. Candidates for `templates/CLAUDE.md` / `templates/visual/snippets.md` and `docs/visual-pipeline.md`.
3. **(c) Reviewer rubric fixes**: where the in-run reviewer and the external score disagree, and the rubric or
   calibration wording that would have caught it in round 1 (`.claude/agents/visual-reviewer.md`, `docs/visual-pipeline.md`
   section 3).
4. **(d) Wasted-token report and baseline**: cost and tokens from the stream-json result's `modelUsage`
   (`build/headless/<id>.stream.jsonl`, every result segment: input, output, cache read/creation, cost), turns, wall
   and active time; per-stage time from commit timestamps (cost share ~ time share); render time; **rounds-to-pass
   per stage**; what did not help and what would have skipped it. End with a **BASELINE** block.
5. Write `LESSONS.md` from `templates/LESSONS.md`, with **before/after image pairs** (full-size paths under
   `docs/shots/<run>/`) for every major lesson.
6. **External blind score (mandatory)**: the final shots are scored blind on the same rubric, at the ref's display
   size, by someone outside the run. **By default that is a fresh Claude Code session** (a new session in a clean
   checkout, not the run session) given only the refs (`docs/refs/`), the final shots
   (`docs/shots/<run>/<phase>/final/`) and the rubric (kit.json `visual.rubric` with the item descriptions from
   `docs/visual-pipeline.md` section 3): no run history, no PROGRESS.md, no reviews or verdicts, no run report. A human
   or Grok Bot reviewer then **spot-checks** its scores (a few cells, the style item on every shot) and notes
   disagreements, rather than scoring the matrix themselves. Record both score matrices side by side (cells at 4+,
   per-cell deltas) in `LESSONS.md` and the external one, with who spot-checked it, in
   `docs/reviews/<run>-external-blind-score.md`. The external score is the authoritative one and the real backstop:
   the in-run calibration only caps a shot when the reviewer itself writes "mismatch". An in-run pass on the final
   stage is provisional until then (r2: in-run 19/21 at 4+, external 7/21).
7. **Kit PRs** for (b) and (c) on the kit repo this project was created from, linked from `LESSONS.md`.

## Rubric and calibration config
Projects with their own style item (e.g. a rubric with `stylization` instead of the default `style_match`) must set
`kit.json` `visual.calibration.cap_item` to it. `tools/review.py start` now refuses every visual round while
`visual.calibration.required` is true and `cap_item` is not an item of `visual.rubric` (otherwise a "mismatch" would
cap nothing), and the SubagentStop hook rejects verdicts for the same reason. Fix it in kit.json between runs.

## The next run
The next brief starts from the recipe's preset values (BRIEF.md "Known context") and measures **rounds-to-pass per
stage, tokens and cost** (and cost per external 4+ cell) against the previous run's BASELINE.
