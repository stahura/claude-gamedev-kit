# Art bible: PROJECT_NAME

<!-- Produced in the visual-direction session (docs/visual-pipeline.md section 1), approved by the owner before any
build phase. `python tools/art_gate.py` checks it: every section filled, no `<placeholder>` left outside comments,
every listed docs/refs/ image exists, and an Approved line. Short and testable beats long and vague: the
visual-reviewer judges shots against this file and the refs. Changing it after approval needs a new Approved line. -->

## Reference images
<!-- Paths under docs/refs/ (images pasted in chat do not count). At least one per asset class you build: characters,
buildings, vegetation, terrain, UI, plus one lighting-mood image. Say what to take from each and what to ignore. -->
| Image | Reference for | Take from it |
|---|---|---|
| `docs/refs/<file>.png` | <hero character> | <silhouette, proportions, colour blocking> |

## Style target
- Stylized or realistic: <one>
- Named comparables (2-3 shipped titles, films or artists, and what to take from each; for the reviewer only, never
  in generation prompts): <...>
- One sentence a reviewer can test a screenshot against: <...>
- Secondary detail the rubric judges (foliage, props, debris, set dressing): <...>; life (what moves): <...>
- Style slice: size <e.g. 60 x 60 m>, contents <one example of each asset class in scope>, default camera

## Palette
- Primary / secondary / accent (hex; asset cleanup pushes textures toward these): <...>
- Albedo value range (darkest, brightest, sRGB): <e.g. 30-235; never pure black or white>
- Saturation rule: <e.g. environment desaturated, characters and interactables carry the accents>
- Readability: <how important objects separate from the ground: value, hue, rim light>

## Lighting mood
- Time of day, key light direction and colour, sky: <...>
- Contrast, shadow softness, fog density and colour: <...>
- Tone mapping and grade intent: <...> (locked in the style slice, stage A; docs/visual-pipeline.md section 5)

## Material rules
- Workflow: <PBR metal/roughness | stylized ramp | hand-painted>; maps per asset: <...>
- Roughness and metalness ranges: <...>
- Environment surfaces: triplanar or trim sheets plus decals; tiling must not read from <default camera distance>
- Edges and wear: <bevels, baked AO, edge highlights, outline>
- Forbidden: <e.g. baked lighting in albedo, mixed texel densities side by side>

## Budgets per asset class
<!-- Triangles at LOD0, LOD count, texel density (px per metre at LOD0), max texture size, materials per asset. -->
| Class | Tris LOD0 | LODs | Texel density | Max texture | Materials |
|---|---|---|---|---|---|
| Hero character | <...> | <...> | <...> | <...> | <...> |
| Creature or secondary character | <...> | <...> | <...> | <...> | <...> |
| Small prop | <...> | <...> | <...> | <...> | <...> |
| Building | <...> | <...> | <...> | <...> | <...> |
| Foliage | <...> | <...> | <...> | <...> | <...> |
| Terrain (per chunk) | <...> | <...> | <...> | <...> | <...> |
| UI | n/a | n/a | <icon px> | <atlas px> | n/a |

## Scale conventions
- Units and axes: <1 unit = 1 m; +Y up; front faces -Z>
- Reference heights: <hero character 1.8 m, door 2.1 m, storey 3 m, tree 6-12 m, small prop 0.3-0.6 m>
- Pivots: <base centre for characters and props; building pivot at a footprint corner on the grid>
- Grid and snapping for modular kits: <e.g. 1 m grid, wall module 4 x 3 m>
- Default camera (height, distance, FOV) content is judged from: <...>

## Do and don't
<!-- Concrete and visible in a screenshot; point at a ref where possible. -->
| Do | Don't |
|---|---|
| <...> (`docs/refs/<file>.png`) | <...> |

## Approval
<!-- Only the owner writes this line, in the form shown. Claude never adds or edits it. A changed bible needs a new
line; the last Approved line counts. -->
Approved: <name>, <YYYY-MM-DD>
