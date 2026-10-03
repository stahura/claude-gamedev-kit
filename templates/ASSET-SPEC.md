# Asset spec: <asset name>

<!-- One per asset handed to a per-asset agent: copy to docs/assets/<asset>.md and fill in. The agent gets this file
plus ART-BIBLE.md and docs/visual-pipeline.md; assume nothing else. Fan-out only after the gates in
docs/visual-pipeline.md section 6 are met. -->

- Class: <hero character | creature | small prop | building | foliage | terrain | UI> (budget row in the bible)
- Route: <AI generator (characters, creatures, organic hero props only) | modular Blender kit | asset pack>
- Concept / refs: <docs/refs/... (one clean full-body or full-object concept for the AI route)>
- Size and pivot: <height or footprint in m>, pivot <base centre>
- Budget: tris LOD0 <...>, LODs <...>, texel density <...>, max texture <...>, materials <...>
- Rig and animation: <none | rig + clips: ...>
- Paid spend allowed: <service N credits> (only via `tools/paid.py`; stop before it)
- Output: `<path>.glb` (+ LOD files), SOURCES.md line (source, license, hash, prompt or pack name)
- Shots it must pass: <shot-set names> plus a four-view turntable of the asset alone
- Done when: cleanup with the bible grade ran (summary line), budgets met, imports with no warnings, in scale next
  to the bible's reference heights, and the visual-reviewer passed it in the scene next to existing assets (rubric,
  `docs/visual-pipeline.md` section 3; the style lock in CLAUDE.md is the target)
- Don't: <out of scope, things the bible forbids that this asset is prone to>
