<!-- Visual-project snippets. `python tools/init_project.py --visual` (or an addon with "visual": true) replaces each
`<!-- kit:visual-NAME -->` marker line in PLAN.md and CLAUDE.md with the snippet of that NAME below and renumbers the
phases after the inserted P1 (P1 -> P2, ...); without --visual the marker lines are removed. -->
<!-- snippet:visual-rule -->
10. Visual (`docs/visual-pipeline.md`): no build phase before `python tools/art_gate.py` prints ART GATE OK; never
   write the Approved line, never edit ART-BIBLE.md, `docs/refs/` or the kit.json "visual" block during a run, never
   edit `docs/shots/shots.json` after the `RUN_ID-lighting-lock` tag. Visual phases run look-and-fix on the fixed shot
   set, one change at a time, before/after kept, unclear changes reverted; iterations render to the git-ignored
   `docs/shots/_work/`. Each round ends with a visual-reviewer review (`tools/review.py start` snapshots the shots and
   prints the brief with the previous round); rounds per stage are capped by `visual.review_caps` (stage A 3, main
   stage 6 by default). Only the visual-reviewer passes a visual phase (its verdict is captured by the SubagentStop
   hook; `tools/review.py close` refuses without it); a screenshot existing is not a pass. Performance is the
   automated `tools/perf_gate.py` check. Frame the shots and dress the scene to the reference's density
   (vegetation, props, outcrops, the painterly/base surface) **before** shader tuning: a shader judged in an
   under-dressed frame is polished against the wrong target. Lighting stage first; the core asset is prototyped on a
   side track meanwhile and gets its own review budget; per-asset fan-out only after P1 (style slice) is closed.
   **Below bar never halts the run:** a stage at its cap without a pass closes with `tools/review.py close P<N>
   --known-issues` (honest scores, known issues in run-state.json and the run report) and the run continues. An
   in-run reviewer pass on the final stage is provisional until the close-out's external blind score.
<!-- snippet:visual-gate -->

Gate before P0: `python tools/art_gate.py` -> ART GATE OK (ART-BIBLE.md approved by the owner before `RUN_ID-start`).
Visual phases: P1 (kit.json `visual.lock_phase`) and every phase whose line carries `[visual]`.
<!-- snippet:visual-p0 -->
  - (must) render of the shot set (`docs/shots/shots.json`) to PNG works; `art_gate.py --shots` OK; the benchmark
    prints `BENCH avg_fps=<x> low1_fps=<y>` (`tools/perf_gate.py`)
<!-- snippet:visual-p1 -->
- [ ] **P1: Style slice** [visual] (`docs/visual-pipeline.md` section 5; a ~60 x 60 m diorama or the project's equivalent)
  - (must) A, first: hero shot framed on the subject (similar frame share to the ref) and the framed area dressed to
    the reference's density (vegetation, props, outcrops) with the painterly/base surface, compared side by side with
    the ref at the same size; no shader tuning before this.
  - (must) A: slice blocked out at final scale around that dressed area instead of pure placeholders; tone mapping,
    AO, GI, bloom, fog, sky + reflections, grade per the bible; visual-reviewer pass on the stage-A items
    (`P1-visualA-r<N>`, max `visual.review_caps.stage_a` rounds, default 3), or the cap reached (below bar); tag
    `RUN_ID-lighting-lock` (freezes the shot set: framing must be right before it).
  - (must) side track during A: prototype the core asset (the brief's main deliverable) outside the slice shots, so a
    slow lighting stage never zeroes it; its stage gets its own review budget.
  - (must) main stage: one asset per route through cleanup with the bible grade (AI generator via paid.py for a
    character or organic hero prop; a modular kit piece; terrain material; the secondary detail; the core asset),
    each within its budget, placed one at a time in the slice
  - (must) style lock: final shots in `docs/style_reference/`, CLAUDE.md "Style lock" filled (skipped when P1 closes
    below bar)
  - Minimum bar: every rubric item 4+ on every shot (visual-reviewer pass `P1-visual-r<N>`, max
    `visual.review_caps.default` rounds); `perf_gate.py` OK; cleanup summary lines logged; lock committed. At a cap
    without a pass: `python tools/review.py close P1 --known-issues` (below bar, honest scores) and continue.
<!-- snippet:visual-commands -->
# art gate:  python tools/art_gate.py [--shots]
# shot set (look-and-fix, docs/shots/shots.json -> docs/shots/_work/<run>/<phase>/i<N>/, final -> docs/shots/<run>/<phase>/final/):
# perf gate: python tools/perf_gate.py --phase P<N> <bench log>
# asset cleanup:  blender -b -P tools/blender/cleanup_asset.py -- --in raw.glb --out x.glb --height 1.8 --tris N --bible ART-BIBLE.md
<!-- snippet:visual-convention -->
- Visuals follow `ART-BIBLE.md`, `docs/visual-pipeline.md` (gate, look-and-fix, asset routes, style slice) and the
  style lock below. Every visual change is rendered, kept only if clearly better (before/after pair), and passed by
  the visual-reviewer, never by its author.
<!-- snippet:visual-pitfalls -->
- Visual pitfalls (r2; symptom -> cause -> fix -> detect early in `docs/visual-pipeline.md` section 5b):
  - Match the reference's style and scene density first: put the ref and the hero side by side at the same size in
    round 1; dress and frame before tuning any shader.
  - Texel blocks in magnified noise: sample procedural noise via a manual bilinear/trilinear helper, never trust the
    sampler's filter hint; probe a 4x nearest-zoomed crop of a pure noise lookup in the first render.
  - Never build normals from 8-bit finite differences (stair-stepping/banding): analytic slopes or float sources.
  - Reflection speckle/shafts: render the reflection term alone on the lowest grazing shot; check whether a "shaft" is
    a real reflected cloud before chasing it.
  - Unshaded foam must be the brightest non-sky value after tonemapping, or it reads as grey decals.
  - Deep water must land near the bible's deep colour after tonemapping, never navy/near-black: sample it in round 1.
  - Foam trails downstream (wakes, curls); never symmetric target rings around rocks.
  - Near water shows a bed and submerged stones (depth, transparency); a flat glassy near field reads as a lake.
<!-- snippet:visual-style-lock -->
## Style lock
- Reference shots, **new work must match these**: `docs/style_reference/<shot>.png` (one line each: what it shows)
- Canonical files: environment/post <...>, lighting presets <...>, shared materials and shaders <...>, global
  parameters (wind, time of day) <...>
- Asset pipeline: cleanup flags <--bible ART-BIBLE.md --push N --delight N>, budgets (bible), generator prompt
  template <style traits only>
- Review: render the shot set, rubric (kit.json visual.rubric; docs/visual-pipeline.md section 3), visual-reviewer
  pass for every visual change

Never do:
- Surfaces off the bible's style target (photoreal or photoscanned textures in a stylized project)
- Generated or bought assets that skipped cleanup or the visual-reviewer
- Mixing asset styles or sources (several packs or generator styles in one scene)
- Naming other games, studios or their assets in generation prompts: describe traits
- Pure black shadows (or clipped white highlights)
- Uniform random scatter: place in clusters and deliberate compositions
