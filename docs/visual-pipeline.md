# Visual pipeline (any engine, any genre)

Order is fixed; each step is a gate for the next. Paths, the review caps, the rubric items, the pass scores and the
performance thresholds are in `kit.json` -> `visual`. Visual is opt-in: `python tools/init_project.py --visual` (or an
addon such as godot) sets `visual.required` true, copies the bible and shot set and adds the visual phases.

| # | Step | Gate (what proves it) |
|---|---|---|
| 1 | Visual-direction session (attended, ~1 h, before the run) | refs in `docs/refs/`, filled `ART-BIBLE.md` |
| 2 | Art bible approved | `python tools/art_gate.py` -> `ART GATE OK` (before **any** build phase) |
| 3 | Shot set + look-and-fix + art-director review | `docs/shots/shots.json` renders to PNG; `art_gate.py --shots` OK; `perf_gate.py` OK |
| 4 | Style slice, stage A: lighting and post on a small dressed patch (placeholder shapes + one real rock, a few grass cards) | stage-A items pass the visual-reviewer, or its cap (default 3 rounds) is reached; lighting locked and tagged |
| 5 | Style slice, main stage: slice assets (the core asset prototyped on a side track since stage A), then the style lock | every rubric item 4+ on every shot within its own review budget; `docs/style_reference/` + CLAUDE.md "Style lock" committed; at the cap: closed below bar with known issues |
| 6 | Content, fanned out per asset | only after 2-5 (section 6) |

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

**A screenshot existing is not a pass, and the builder never passes its own work.** At every visual phase the
**visual-reviewer** (an independent art director) reviews `final/`. It sees only the shot PNGs, the contact sheet,
`ART-BIBLE.md` with its refs, this rubric and the brief's numbered quality bar. It sees no code, diffs or
`critique.md`, and it writes no code. It scores this round first; only then it opens the previous round's snapshot
and its top problems (never its old scores), rates every shot better, same or worse (`"vs_previous"` in its verdict) and does not reverse its own earlier requests unless the change made a shot
worse (and then says so): r1's reviewer oscillated without a before/after. Its verdict, not the author's critique,
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
| `cohesion` | No asset looks more realistic, noisier, sharper or differently scaled than its neighbours |
| `secondary_detail` | The project's secondary detail (foliage, props, debris, set dressing; named in the bible) reads as one style; no alpha or LOD artefacts |
| `ground` | Ground and terrain blend with what stands on it; no seams, stretching or visible tiling |
| `life` | Ambient motion is present where the bible asks for it (wind, particles, idle animation, water) |

Stage A of the style slice (lighting, review id `<phase>-visualA-r<N>`) scores `visual.stage_a_items` (default
silhouette, depth, light, palette) against `visual.stage_a_min_score` (default: `rubric_min_score`); the others may be
`n/a` until real assets exist. Keep the stage-A items to what lighting can fix (light, palette, depth): r1 spent all
its rounds scoring `stylization` on placeholder shapes. Every other visual review (`<phase>-visual-r<N>`) scores every
item; `n/a` is rejected.

**Performance is an automated gate, not a rubric item.** The benchmark prints `BENCH avg_fps=<x> low1_fps=<y>`
(Godot: `render_shots.gd -- --bench=<frames>`; other engines print the same line) and
`python tools/perf_gate.py --phase P<N> <log>` checks it against `kit.json` `visual.perf` (`min_avg_fps`,
`min_low1_fps`; null for offline or asset-only projects, which check the bible's budgets in their tests).
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

**Stage A: lighting and post on a small dressed patch.** Block the slice out at final scale in primitives (a 1.8 m
figure, boxes for buildings, spheres and capsules for secondary detail, a plane or rough heightmap for ground), and
dress one small patch with real surfaces (one real rock, a few grass cards, the ground material): lighting judged on
pure placeholders reads flat and the reviewer cannot score it fairly. Set, then lock (commit + tag
`<run>-lighting-lock`):
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
| Verdict capture is observable | every SubagentStop call (and every Stop decision and guard deny) is a line in `.claude/run-state/hooks.log.jsonl`; a reviewer that handed back without a storable verdict is recorded `invalid` at once |
| Performance | `tools/perf_gate.py` record, required by the close check |
| Repeatable shots | `render_shots.gd`: seeded RNG, frozen time, PNG size asserted |

These stop accidents and shortcuts, not intent: the builder can still run arbitrary code (python, `blender -P`,
`godot -s`) and writes the reviewer's prompt. The containment for intent is in the README.
