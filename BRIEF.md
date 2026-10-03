# Brief: PROJECT_NAME, run RUN_ID

<!-- Written by the orchestrating bot. One brief per run. Claude reads it unattended: answer every question here.
Handoff line: Read BRIEF.md in <owner>/<repo> on branch <run-branch>; run it unattended per the run-protocol skill;
report via run-report.json. -->

## Goal
<!-- 2-3 sentences: the user/player outcome, not the implementation. -->

## Non-negotiables
<!-- Owner decisions Claude must not reopen (engine, style, scope limits, names). -->

## Definition of done
<!-- Each item testable by a script or a screenshot rubric. Say how it is measured. -->
1.

## Quality bar
<!-- Numbered and measurable. Reference images committed under docs/refs/ (images pasted in chat are not available
to an unattended run). -->
1.

## Art bible and visual pipeline
<!-- Visual projects only (initialised with --visual or a visual addon); otherwise write "not a visual project". -->
- Art bible: `ART-BIBLE.md` (from the visual-direction session); approval line present: <yes, name and date>
- Shot set: `docs/shots/shots.json` version <N> (or "write in P0 from the bible's shot list")
- Review rounds: `kit.json` `visual.review_caps` = <stage_a 3, default 6, phases {...}> (per stage; stage A rounds
  never eat the main stage's budget); at a cap without a pass `visual.on_cap` = proceed_with_known_issues: the phase
  closes below bar (`tools/review.py close P<N> --known-issues`) with honest scores and the run continues. Rubric
  pass score `visual.rubric_min_score` = <4> (stage A: `visual.stage_a_min_score` = <4>); rubric items
  `visual.rubric` = <default 3D set | your own>; stage-A items `visual.stage_a_items` = <lighting/palette items>;
  performance: `visual.perf` = <e.g. avg 60, 1% low 30 fps at 1080p on the benchmark path | null, bible budgets>
- Style slice (P1, before any content): <size, e.g. 60 x 60 m or equivalent; contents>. Lighting first on a small
  dressed patch (one real rock, a few grass cards), the core deliverable (<e.g. the water shader>) prototyped on a side
  track meanwhile, then slice assets, then the look is locked in CLAUDE.md and `docs/style_reference/`.
- Asset routes: AI generator only for characters, creatures, organic hero props; environments from modular Blender
  kits; third-party pack: <none | name, license>; every AI-generated asset through Blender cleanup with the bible
  grade. Details: `docs/visual-pipeline.md`.
<!-- No build phase starts without an approved art bible (`python tools/art_gate.py`), approved before the
`<run>-start` tag; the bible, refs and kit.json "visual" are frozen during the run. -->

## Scope
- Must:
- Stretch:
- Out of scope:

## Budget
- Paid APIs (also set in kit.json): <service> cap <N>
- Wall-time ceiling:
- Test budget (smoke suite time/frames):

## Allowed assets and licenses
<!-- e.g. CC0 only: Poly Haven, Kenney, Quaternius; Meshy for unique characters. Record sources in SOURCES.md. -->

## Known context
- Last run report: <!-- path to run-report.json -->
- Known issues to fix first:

## Questions already answered
<!-- Everything Claude would otherwise stop to ask. A below-bar visual stage never stops the run (kit default); do not
write "stop the run if the bar is not met". Headless: anything off the allowlist is denied and logged, never asked. -->

## Deliverables the bots will read
- run-state.json, run-report.json, RUN-REPORT.md, PROGRESS.md
- Release: <run>-build prerelease
- Screenshots / contact sheets: docs/shots/<run>/
