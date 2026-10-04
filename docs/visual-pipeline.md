# Visual pipeline (any engine, any genre)

Order is fixed; each step is a gate for the next. Paths, the review caps, the rubric items, the pass scores and the
performance thresholds are in `kit.json` -> `visual`. Visual is opt-in: `python tools/init_project.py --visual` (or an
addon such as godot) sets `visual.required` true, copies the bible and shot set and adds the visual phases.

| # | Step | Gate (what proves it) |
|---|---|---|
| 1 | Visual-direction session (attended, ~1 h, before the run) | refs in `docs/refs/`, filled `ART-BIBLE.md` |
| 2 | Art bible approved | `python tools/art_gate.py` -> `ART GATE OK` (before **any** build phase) |
| 3 | Shot set + look-and-fix + art-director review | `docs/shots/shots.json` renders to PNG; `art_gate.py --shots` OK; `perf_gate.py` OK |
| 4 | Style slice, stage A: frame the shots and dress the scene to the reference's density (vegetation, props, outcrops, the painterly/base surface), then lighting and post | framing and density judged against the ref in round 1; stage-A items pass the visual-reviewer, or its cap (default 3 rounds) is reached; lighting locked and tagged |
| 5 | Style slice, main stage: slice assets and the core asset's shader tuning (prototyped on a side track since stage A), then the style lock | every rubric item 4+ on every shot within its own review budget; `docs/style_reference/` + CLAUDE.md "Style lock" committed; at the cap: closed below bar with known issues |
| 6 | Content, fanned out per asset | only after 2-5 (section 6) |
| 7 | Close-out (after every run, same session) | `LESSONS.md`, recipe, pitfalls, rubric fixes, token baseline, external blind score; [`docs/close-out.md`](close-out.md) |

Projects with no visual output (CLI, backend, library) are initialised without `--visual`: `visual.required` stays
false, the art gate prints SKIPPED and the plan has no visual phases. Section 7 lists what is enforced mechanically.

## 1. Visual-direction session (~1 hour, owner + one agent)
- **Inputs:** the brief's goal and non-negotiables, 3-10 owner-picked images or titles, target platform and camera.
- **Do:** generate concept images (any image generator; paid ones only through `tools/paid.py`) for: a hero
  character, a building, vegetation, terrain and a UI mock, plus one lighting-mood frame. Iterate on the few that are
  closest; for anything that will go through an AI 3D generator, make one clean full-body or full-object concept on a
  plain background.
- **Outputs:** picked images in `docs/refs/` (descriptive names), `ART-BIBLE.md` filled from `templates/ART-BIBLE.md`,
  the shot list (names, what each judges, which refs) for `docs/shots/shots.json`, and the style slice's size and
  contents (section 5).
- **Exit criteria:** every bible section filled with testable rules; at least one ref per asset class in scope; the
  owner adds `Approved: <name>, <YYYY-MM-DD>` under `## Approval`; `art_gate.py` prints OK; committed.

## 2. Art bible gate
- No build phase starts until `python tools/art_gate.py` prints `ART GATE OK`. Re-check at the start of every run.
- Only the owner writes the Approved line. Claude never adds, edits or "fixes" it, attended or not.
- The gate is anchored to git tags (run id = `kit.json` "run"): it fails unless the Approved line was already in
  `ART-BIBLE.md` at the `<run>-start` tag, and if `ART-BIBLE.md`, `docs/refs/` or the kit.json `visual` block changed
  since that tag (working tree, untracked files included). Once `<run>-lighting-lock` exists, `docs/shots/shots.json`
  is frozen too (P0 may still write it). A bible, ref or shot-set change is an owner commit between runs.
- `--draft` checks the content only (for the visual-direction session) and never prints `ART GATE OK`.
- A run that finds the gate failing does not build (run-protocol section 0); it reports why.

## 3. Shot set, look-and-fix loop and the art-director review (every visual phase)
The shot set (`docs/shots/shots.json`, from `templates/shots.json`) is fixed and versioned: named cameras, scene,
resolution, settle frames, and the refs each shot is judged against. Bump `version` on any change; compare only
renders of the same version. Never move a camera to hide a problem.

**Rounds.** One round = the loop below, then one visual-reviewer review of `final/`. Rounds are capped per stage by
`visual.review_caps` (see "Review caps" below): stage A (`<phase>-visualA-r<N>`) 3, the main stage
(`<phase>-visual-r<N>`) 6 by default. Within a round, iterate as long as changes are clearly better.
1. Render every shot to `docs/shots/_work/<run>/<phase>/i<N>/<shot>.png` (git-ignored; deterministic: fixed
   exposure, fixed time of day, seeded scatter and RNG, settle frames, then time frozen for the capture; the saved PNG
   must have the set's resolution). Build the contact sheet.
2. Open every full-size PNG next to its refs. Write `critique.md` in the same folder: your own rubric scores (below)
   per shot and the three biggest problems.
3. Fix **one focused change at a time** (parameters, materials, placement before rewrites). Re-render the affected
   shots (`--only`) and compare with the render before it. Keep the change only if it is clearly better; otherwise
   revert it. For each kept change, commit the pair in `docs/shots/<run>/<phase>/changes/<NN>-<what>/before|after/`
   and name the visual change in the commit message.
4. Re-render the whole set into `i<N+1>`. Stop when every shot meets the rubric or nothing more is clearly better.
5. Copy the last iteration (and its contact sheet) to `docs/shots/<run>/<phase>/final/` and commit it. Only `final/`,
   `changes/` and the review snapshots `rounds/<id>/` are committed; per-iteration renders stay in
   `docs/shots/_work/` (git-ignored) so the repo does not grow by a full shot set per iteration.
6. `python tools/review.py start <id>`: accepts only the stage's next round number, refuses once the stage has used
   its cap of reviewed rounds, copies `final/*.png` to `docs/shots/<run>/<phase>/rounds/<id>/` and prints the reviewer
   brief (also `rounds/<id>/review-brief.md`): this round's folder and the previous round's folder. The previous
   round's top problems and findings go to `rounds/<id>/previous-round.md`, **without its scores** (numbers are
   scrubbed from the text too); the reviewer opens it only after it has scored this round (anti-anchoring). Launch
   the visual-reviewer with that brief.

**Look-and-fix pitfalls (r2; each cost rounds).**
- **Before tuning any hero asset, put the reference and the hero shot side by side at the same size** and compare
  coverage and density. A well-tuned asset inside an under-dressed frame still fails the style items (r2: 6 water
  rounds could not lift external stylization above 2-3).
- **A fix for one shot can break another**: after any change to a shared mapping (a reflection or projection term, a
  fog or exposure setting, a global sampler), re-render the most sensitive shot (for reflections: the lowest, most
  grazing camera) before committing. r2's flatter reflection dome fixed the close shot and killed the low shot's
  reflection for a round.
- **Isolate the term before guessing**: render the suspect term alone (e.g. the reflection with the body colour off)
  on the fast set. r2 spent three full renders on wrong hypotheses for one artefact.
- **Probe for engine-level artefacts in the first iteration**: a 4x nearest-scaled crop of a magnified procedural
  texture (square texel blocks mean the sampler is not filtering); never derive normals from 8-bit finite
  differences; measure that the brightest intended element (foam, highlights) is the brightest non-sky value after
  tone mapping, and that the darkest is not near black.
- **Never edit files during a multi-shot render**: later shots pick up the edit and the set is invalid.
- Keep a fast shot set (few settle frames) for iteration from minute one; review rounds use the full set.

**A screenshot existing is not a pass, and the builder never passes its own work.** At every visual phase the
**visual-reviewer** (an independent art director) reviews `final/`. It sees only the shot PNGs, the contact sheet,
`ART-BIBLE.md` with its refs, this rubric and the brief's numbered quality bar. It sees no code, diffs or
`critique.md`, and it writes no code. It scores this round first; only then it opens the previous round's snapshot
and its top problems (never its old scores), rates every shot better, same or worse (`"vs_previous"` in its verdict) and does not reverse its own earlier requests unless the change made a shot
worse (and then says so): r1's reviewer oscillated without a before/after.

**Calibration against the reference (every round, before the shots).** r2's in-run reviewer scored 19/21 shot-items
at 4+ where an external blind score gave 7/21: it went deep on water micro-flaws, never compared the whole frame
with the dense, painterly reference, and the frame was ~60 % bare meadow. So the reviewer first scores the
reference image itself on the rubric (an anchor, ~5), then judges each shot's **whole frame** against its ref at the
ref's display size (~800 px, side by side) before zooming in: overall style and scene density/composition (how much
of the frame the subject covers, vegetation, props, framing). Any style or density mismatch caps the style item
(`kit.json` `"calibration": {"required": true, "cap_item": "style_match", "cap": 3}`; set `cap_item` to the project's
style item, e.g. `stylization`) at 3 for that shot. The verdict records it as `"calibration": {"reference": {...},
"shots": {shot: "match: ..." | "mismatch: ..."}}`; `kitlib.calibration_problems` rejects a missing one (when
required), a shot without a judgement, and a mismatched shot scored above the cap. `cap_item` must be an item of
`visual.rubric`: otherwise a mismatch would cap nothing, so `review.py start` refuses every visual round and the hook
rejects every verdict until kit.json is fixed. Projects with their own style item (a rubric with `stylization`) set
`cap_item` to it.

**`vs_previous` is blind (kept, not dropped).** r2's `vs_previous` said "better" on every shot of every main round
while the distance to the reference barely moved: anchoring on round-over-round improvement. Dropping it would also
drop the before/after check that stopped r1's oscillation, so it stays but cannot move a score: the reviewer writes
its blind scores (```json {"blind_scores": {shot: {item: n}}}```, every shot x item of its verdict) before it opens
`previous-round.md` or any earlier round's PNG, and only then compares. The SubagentStop hook rejects a verdict that
opened the previous round before the blind block, whose blind block misses any scored cell, or that scores any cell
above its blind score (the comparison can lower a score for a named flaw, never raise
it). `vs_previous` also says what still separates each shot from the reference.

**Check in round 1, not late** (the r2 reviewer raised these in main r2 to r6, or never): framing and composition vs
the ref, while the shot set can still change (before the lighting lock); foam/wake direction (downstream wakes and
curls readable in a still, not symmetric halos); bed and depth cues in near water or any see-through surface; and the
grazing-angle reflection, judged on the lowest grazing shot first.

**An in-run pass is provisional.** On the final round of the core stage the brief reminds the reviewer that r2's
in-run scores were ~12 of 21 cells more lenient than an external blind score; a pass there stands only after an
external blind score in the close-out ([`docs/close-out.md`](close-out.md)). The calibration verdict is only as
honest as the reviewer (a lenient one writes "match"), so the external blind score stays mandatory.

The visual-reviewer's verdict, not the author's critique,
closes the phase: a SubagentStop hook stores its JSON verdict (the builder never supplies it), read from its last
message, its `SubagentHandback` message or its last text (background subagents end with the handback tool; the
reviewer writes the verdict in both), and `tools/review.py close` refuses to mark a visual phase `[x]` without a
stored pass. The builder fixes its top 3 problems or logs why not.

**Review caps and below bar.** `kit.json`:
```json
"review_caps": {"stage_a": 3, "default": 6, "phases": {"P1": {"A": 3, "": 8}, "P3": 5}},
"on_cap": "proceed_with_known_issues",
"rubric_min_score": 4, "stage_a_min_score": 4
```
`stage_a` caps every stage A, `default` every main stage; `phases` overrides per phase (an object with `"A"` and `""`
for the two stages, or a number for the main stage). `look_fix_max_iterations` is retired: when present and
`review_caps.default` is not, it is read as the main-stage cap. **Only reviewed rounds count** against the cap (a
verdict captured by the hook); rounds start strictly in order (`start` refuses r6 when r2 is next), and two rounds in
a row of one stage without a captured verdict (invalid, unreviewed or abandoned) set `run-state.json` status
`blocked` with a `blocked_reason`: the watcher exits 3 and the orchestrator picks up, instead of burning the budget on
reviews that never land. **Below bar never halts the run.** A stage at its cap without a pass is closed below bar
(`--known-issues` is refused unless the stage has at least one captured verdict): `python tools/review.py close P<N> --known-issues` marks the phase
`[x] (below bar)` and records `status: done_below_bar`, `known_issues` (the last verdict's top problems),
`last_scores` and the rounds in `run-state.json` (and `run-report.json` if it exists); later phases then close
normally and the Stop hook keeps the run going. Honest scores only: the stored verdict stays `fix_needed`; nothing is
marked a pass. `"on_cap": "mark_skipped"` instead has the phase marked `[-]` with its known issues (the run still
continues).

**Review order (every round; summary of the rules above).**
1. **Score the reference itself** on the rubric (the main ref of each shot). It should land near 5; if it does not,
   the reviewer's scale is off and it says so.
2. **Calibration**: one `match:`/`mismatch:` judgement per shot on overall style and scene density vs the reference
   (vegetation/prop density, rock outcrops, brushwork or surface texture, the hero subject's share of the frame),
   judged on the **whole frame at the reference's display size first** (about 800 px wide, side by side), then the
   full-size crops. A mismatch caps `visual.calibration.cap_item` at the cap, however good the hero asset is.
3. Write the blind scores, with `distance_to_ref` per shot (what is still missing versus the reference; optional
   verdict field). Only then open the previous round for `vs_previous`, which can lower a score, never raise it:
   "better" is not a reason for a 4.
4. **Check from round 1**, not when they happen to come up: the hero subject's share of the frame (before the
   lighting lock freezes the shot set); for motion items (flow, wind, foam) that a **still** shows the direction as
   well as the strip showing motion; for reflections, the **lowest / most grazing shot first**; for water or glass,
   near-field depth cues (bed, submerged objects) rather than a flat opaque sheet.
5. **External blind score at the end** (close-out): lessons and recipes mark a value validated only when it and the
   in-run score agree; an in-run-only 4 is "contested".

### Art-director rubric (per shot, 1-5; pass = every item at least `visual.rubric_min_score`, default 4)
The items are `kit.json` `visual.rubric` (keys below) and the stage-A subset `visual.stage_a_items`; the defaults
suit a 3D world. A 2D, UI or product project replaces them with its own (and describes them in the bible) before the
run; the verdict must score every shot of the current set on every item.

| Item | 5 means |
|---|---|
| `silhouette` | Shapes read at a glance from the default camera distance; no clutter or noise |
| `depth` | At least three readable layers (fore, mid, back) separated by value, haze or fog |
| `light` | One clear key direction; lit and shadow areas carry the bible's colour temperatures; no pure black |
| `palette` | Colours and values inside the bible's palette and albedo range; nothing oversaturated, grey-mush or clipped |
| `cohesion` | No asset looks more realistic, noisier, sharper or differently scaled than its neighbours (assets match each other) |
| `style_match` | Whole-frame style, density and framing vs the refs: brushwork/texture and shading treatment, scene density (vegetation, props, outcrops), the subject's share of the frame; judged side by side with the ref at its display size (the default calibration cap item). A frame can be perfectly cohesive and still the wrong style |
| `secondary_detail` | The project's secondary detail (foliage, props, debris, set dressing; named in the bible) reads as one style; no alpha or LOD artefacts |
| `ground` | Ground and terrain blend with what stands on it; no seams, stretching or visible tiling |
| `life` | Ambient motion is present where the bible asks for it (wind, particles, idle animation, water), visible in a strip **and** readable as a direction in a still |

Project-specific items (e.g. a water project's `stylization`, `foam`, `flow`, `sky_reflection`, `depth_gradient`)
are described in the bible with the same precision. Wording that r2 lacked and needed:
- `stylization`: the frame's style, subject coverage and density match the reference (the hero covers a similar
  share of the frame); set it as `visual.calibration.cap_item` so a mismatch caps it.
- `foam` (or any directional effect): reads as downstream wakes and curls with a visible flow direction in a still
  (asymmetric, trailing behind obstacles), not rings or halos around them.
- `flow`: motion between strip frames **and** a readable direction in a single still.
- `depth_gradient` (water, glass): the near field shows the bed and submerged objects; not a flat opaque sheet.
- `sky_reflection`: judged on the lowest grazing shot first.

Stage A of the style slice (lighting, review id `<phase>-visualA-r<N>`) scores `visual.stage_a_items` (default
silhouette, depth, light, palette) against `visual.stage_a_min_score` (default: `rubric_min_score`); the others may be
`n/a` until real assets exist. Keep the stage-A items to what lighting can fix (light, palette, depth): r1 spent all
its rounds scoring `stylization` on placeholder shapes. Every other visual review (`<phase>-visual-r<N>`) scores every
item; `n/a` is rejected.

**Performance is an automated gate, not a rubric item.** The benchmark prints `BENCH avg_fps=<x> low1_fps=<y>`
(Godot: `render_shots.gd -- --bench=<frames>`; other engines print the same line) and
`python tools/perf_gate.py --phase P<N> <log>` checks it against `kit.json` `visual.perf` (`min_avg_fps`,
`min_low1_fps`; null for offline or asset-only projects, which check the bible's budgets in their tests, and for runs
on a machine without a GPU: software rendering is valid for look review but its fps mean nothing, so the perf gate is
deferred and the report says perf was not measured).
`review.py close` requires its record for visual phases when thresholds are set.

## 4. Asset pipeline
| Asset kind | Route |
|---|---|
| Characters, creatures, organic hero props | AI 3D generator (Meshy or similar), **only via `tools/paid.py` and its caps**: one clean full model from one concept image, never separate pieces stitched together. Prompts describe style traits, never another game |
| Environments, architecture, modular props | Scripted modular Blender kits on the bible's grid; triplanar or trim-sheet shaders; decals for wear and variation. Not AI generated |
| Terrain | Heightmap or sculpt + triplanar/splat materials from the bible palette |
| Optional third-party pack | Only one coherent pack that already matches the bible; license and source recorded in SOURCES.md; still through cleanup |

Every generated or bought mesh then goes through headless Blender (**mandatory for every AI-generated asset**):
```
blender -b -P tools/blender/cleanup_asset.py -- --in raw.glb --out asset.glb --height 1.8 --tris 20000 --bible ART-BIBLE.md
```
fix scale and pivot -> merge/clean -> decimate to budget -> clean UVs -> rebake -> **grade**: strip baked-in lighting
from the base colour (low-frequency light and shadow divided out, `--delight`) and push it toward the bible's palette
and albedo value range (`--push`, read from `## Palette`) -> LODs -> GLB. It prints one JSON summary line (size, tris
per LOD, graded textures) for the asset's spec and SOURCES.md. Then a four-view turntable render, and the asset is
judged **in the scene next to existing assets**: one that looks fine alone but clashes in the shots is rejected.

## 5. Style slice: lighting first, then slice assets, then the style lock (before any content)
A small diorama, about 60 x 60 m or the project's equivalent (one room, one street, one arena, one product shelf),
that must hit the art bible before content work starts. Its size and contents come from the visual-direction
session: one example of each asset class in scope, the default camera, the shot set.

**Dress and frame before shader tuning.** Scene dressing (vegetation, props, rock outcrops at the reference's
density) and the painterly/base surface come **before** tuning the core asset's shader: a shader stage judged in an
under-dressed frame is polished against the wrong target. r2 spent six water rounds (108 min, ~$15) on a frame that
was ~60 % bare meadow next to a dense painterly ref; the external stylization score stayed at 2-3 whatever the water
did. Frame the hero shot on the subject (it should cover a share of the frame similar to the ref) before the lighting
lock freezes the shot set, and put the ref and the hero side by side at the same size in round 1.

**Stage A: lighting and post on a dressed patch.** Block the slice out at final scale in primitives (a 1.8 m
figure, boxes for buildings, spheres and capsules for secondary detail, a plane or rough heightmap for ground), and
dress the framed area with real surfaces at the reference's density (rocks, grass and flower clumps, the ground
material): lighting judged on pure placeholders or a bare patch reads flat and the reviewer cannot score it fairly.
Set, then lock (commit + tag `<run>-lighting-lock`):
- [ ] Tone mapping: filmic or AgX (ACES-like); fixed exposure for shots (no auto exposure in the shot set)
- [ ] Ambient occlusion (screen-space or baked)
- [ ] Global illumination appropriate to the engine and scene (dynamic, probe-based or baked)
- [ ] Glow/bloom, subtle; only emissives and highlights bloom
- [ ] Fog (distance and/or height; volumetric if the mood needs it); distant layers fade toward the fog/sky colour
- [ ] HDRI sky (or physical sky) lighting ambient and reflections; reflection probes or screen-space reflections
- [ ] Shadows: cascades and softness matching the mood; shadows tinted, never pure black
- [ ] Colour grade (LUT or adjustments) matched to the bible's palette and mood ref
- [ ] Stage-A shots pass the visual-reviewer (stage A items), or stage A reaches its cap (default 3 rounds) and stays
      below bar. Great lighting must already feel like the mood ref; if it does not, assets will not save it. The lock
      tag also freezes the shot set (section 2).

**Core deliverable on a side track.** While stage A iterates, prototype the brief's core asset (the water shader, the
hero character) on a side track: its own test scene or branch, outside the slice shots. A slow lighting stage then
never zeroes the deliverable (r1 spent every round on stage A and never built the water). The core asset's stage has
its own review budget regardless of how stage A ended.

**Order inside the main stage: dressing and surface style before core-asset polish.** Bring the slice's dressing
and ground surface to the reference's density and style first; only then polish the core asset (shader rounds) in
it. A core asset judged inside an under-dressed frame gets polished against the wrong target.

**Main stage: slice assets.** Replace the placeholders with real assets through section 4, one per route in scope (an
AI-generated character or organic hero prop, a modular kit piece, the terrain material, the secondary detail),
one at a time, each checked in the slice. Gate: every rubric item at least the minimum on every shot, visual-reviewer
pass.

**Style lock.** When the main stage passes: copy the final shots to `docs/style_reference/` and fill the "Style lock" section
of `CLAUDE.md` (reference shots labelled "new work must match these", canonical environment/material/shader files,
cleanup flags, the never-do list); update the bible's palette with the values actually used (the owner re-approves).
After the lock, changing any lighting or post setting needs a full shot-set re-render and a new sign-off.

**A style slice at its caps closes below bar; the run continues.** If a stage ends its rounds without a stored
visual-reviewer pass, P1 closes with `--known-issues` (honest last scores, open problems and round counts in
run-state.json and the run report), the style lock is skipped and content matches the best state reached. Later
phases may close only after P1 is closed (`[x]`, below bar included) or marked `[-]`.

| Setting | Godot 4 (see the godot addon skill) | Unity URP / HDRP | Unreal 5 |
|---|---|---|---|
| Where | `WorldEnvironment` + `Environment` + `CameraAttributes` resources | Global Volume profile | Post Process Volume (Infinite Extent) + World settings |
| Tone map / exposure | `tonemap_mode` Filmic/AgX; `CameraAttributesPractical` fixed | Tonemapping (ACES/Neutral); HDRP Exposure Fixed | Filmic tonemapper; Exposure Metering Manual |
| AO | `ssao_enabled` | URP SSAO renderer feature; HDRP Ambient Occlusion | Lumen / SSAO |
| GI | SDFGI, VoxelGI or LightmapGI | Lightmaps / Adaptive Probe Volumes; HDRP SSGI | Lumen GI |
| Bloom | `glow_enabled` | Bloom | Bloom |
| Fog | `fog_enabled`, volumetric fog | URP Lighting fog; HDRP Fog (volumetric) | Exponential Height Fog (+ volumetric) |
| Sky / reflections | `PanoramaSkyMaterial` HDRI, `ssr_enabled`, `ReflectionProbe` | Skybox/HDRI Sky, Reflection Probes, HDRP SSR | HDRI Backdrop or Sky Atmosphere, Lumen reflections |
| Grade | `adjustment_*`, `adjustment_color_correction` LUT | Color Adjustments, Color Lookup | Color Grading, LUT |
| Shots | `render_shots.gd` | Editor script rendering each camera to a RenderTexture (batchmode with a GPU, not `-nographics`) | Movie Render Queue or `HighResShot` |

## 5b. Pitfalls (symptom -> cause -> fix -> detect early)
From a pilot run, r2 (a stylized river scene, Godot 4, Forward+; details and before/after pairs in that project's `LESSONS.md`). Most
apply to any stylized surface shader.

| Pitfall | Symptom | Cause | Fix | Detect early |
|---|---|---|---|---|
| Scene style/density mismatch (the big one) | Detailed water scored 4 in-run, stylization 2-3 externally; "clean low-poly with a bare lawn" next to a dense painterly ref | Brief scoped a small dressed patch; no rubric step compared the whole frame with the ref | Dress to the ref's density and set the painterly surface before shader tuning; frame the hero on the subject before the lighting lock | Round 1: ref and hero side by side at the same size; compare subject coverage, foliage density, number of distinct value/texture regions; reviewer calibration (section 3) |
| Texel-block noise | Square, screen-aligned 3-6 px blocks in magnified noise (grazing reflections), read as "blocky / stair-stepped" for 3 rounds | A shared/global noise sampler ignored its filter hint and sampled nearest when magnified | Sample procedural noise through a manual bilinear lookup (texelFetch + smoothstep weights) and a trilinear helper picking the mip from `dFdx/dFdy * textureSize` | First shader render: one magnified close-up of a pure noise lookup, crop zoomed 4x with nearest scaling; visible squares = unfiltered sampler |
| 8-bit stair-stepping / banding | Banded, stepped contours in reflections or shading | Normals from finite differences of an 8-bit (L8) noise texture: slopes quantised to 1/255 | Never build normals from 8-bit finite differences; use analytic slopes (sums of sines in flow space) or a float/16-bit source | 4x crop of the reflection in the first render |
| Reflection speckle and "shafts" | Per-pixel orange/grey speckle; blocky contours near the horizon; pale vertical shafts at grazing angles | High-frequency ripple feeding the sky lookup; a projection that explodes near the horizon; stretched light dabs, **or the true reflection of a cloud** | Low-frequency ripple calmed near the camera; clamp the reflected elevation for clouds (keep the true one for the gradient); soft, wide cloud coverage; isotropic dabs | Before chasing a "shaft", render the reflection term alone (body colour off) on the lowest grazing shot with clouds overhead: a real reflected cloud is not a bug (r2 lost three renders on this) |
| Grey foam reads as decals | "Paper cut-outs", then "grey filled halos", "chunky grey decals" | Unshaded foam at ~0.9 linear lands near mid-grey after AgX/filmic at a low exposure; filled contact discs and wide shallow lightening | Push foam energy so it is the brightest non-sky value (r2: 1.7); narrow contact band; little shallow lightening around rocks | Probe the foam pixels in the first render: brightest non-sky value in the frame |
| Navy / near-black deep water | "Dark navy", "ultramarine blotches", flat navy foreground | Linear albedo through the tonemapper at the fixed exposure; dark dabs merging at distance | Raise brightness, move the deep colour toward the bible's teal, fade dark dabs with distance, fresnel sky lift at grazing angles | Sample the deep-water pixel in round 1: the bible's deep colour within ~10 % after tonemapping |
| Symmetric target rings | "Target rings", "symmetric halos" around every rock, flagged for four rounds | Foam built from radial distance around obstacles (even downstream-only rings stay rings) | Build foam from a downstream wake field with curl lobes, gathering along the banks | A still must show which way the water flows; compare with the ref's foam direction |
| Flat glassy near field | Near water is "one flat blue... reads as a lake"; no bed, no submerged stones | Colour only from bank distance; opaque near field; no refraction | Depth-based transparency and refraction, bed colour, submerged stones | The grazing shot's lower third shows a bed colour change or a submerged stone |
| Files edited mid-render | Later shots of a multi-shot render differ from the earlier ones; a polluted baseline | The renderer reloads scenes/shaders per shot while files change | Never edit files the render reads until it finishes; queue edits, or render from a clean worktree | Compare the set's first and last shot timestamps with the last edit; re-render any set that overlapped an edit |

Process: wait on log text, not `until ! pgrep -f <pattern>` (it matches itself); build contact sheets from the
iteration folder, not from `final/` holding an old `contact.png`; pass `--audio-driver Dummy` on boxes without sound
so ALSA errors do not fail checks.

## 6. Parallelism rule
Fan out to per-asset agents **only** when all of these exist: approved bible (gate OK), the shot set rendering with
look-and-fix working, and the style slice closed: passed and locked (lighting locked, one asset per route through the
pipeline, `docs/style_reference/` and the CLAUDE.md style lock committed), or closed below bar with its known issues
(then the best state's `final/` shots are the reference). Before that, one agent works serially. Each
asset agent gets a filled `templates/ASSET-SPEC.md` (copied to `docs/assets/<asset>.md`) plus `ART-BIBLE.md` and the
style lock, runs its own look-and-fix loop on its shots, and stays within the spend in its spec. The main session
integrates, re-renders the whole shot set, and has the visual-reviewer sign off.

## 7. What is enforced, and how
| Rule | Mechanism |
|---|---|
| No self-pass | Visual verdicts are captured from the visual-reviewer's transcript by `.claude/hooks/subagent_stop.py` (full score matrix, current `shot_set_version`, every shot PNG opened); `review.py done` refuses visual ids; Write/Edit and shell writes to `.claude/run-state/` are denied |
| A visual phase closes only on a pass | `python tools/review.py close P<N>`; the Stop hook flags any `[x]` that fails the same check |
| Approved bible, frozen inputs | `tools/art_gate.py` against the `<run>-start` and `<run>-lighting-lock` tags; the guard denies moving or deleting tags |
| Review caps; below bar never halts the run | `review.py start` refuses rounds past `visual.review_caps`; `close --known-issues` records `done_below_bar`; the Stop hook tells the builder to close below bar and continue |
| Reviewer sees the previous round | `review.py start` snapshots `rounds/<id>/` and prints the brief; the hook accepts the previous round's PNGs next to this round's full set |
| Blind comparison | the SubagentStop hook rejects a verdict that opened the previous round before its `blind_scores` block, a blind block missing any scored cell, or scores above it |
| Calibration against the ref | `kitlib.calibration_problems`: `calibration` required (kit.json `visual.calibration`), one match/mismatch per shot, mismatch caps the style item; `review.py start` refuses rounds while `cap_item` is not a rubric item |
| Verdict capture is observable | every SubagentStop call (and every Stop decision and guard deny) is a line in `.claude/run-state/hooks.log.jsonl`; a reviewer that handed back without a storable verdict is recorded `invalid` at once |
| Performance | `tools/perf_gate.py` record, required by the close check |
| Repeatable shots | `render_shots.gd`: seeded RNG, frozen time, PNG size asserted |

These stop accidents and shortcuts, not intent: the builder can still run arbitrary code (python, `blender -P`,
`godot -s`) and writes the reviewer's prompt. The containment for intent is in the README.
