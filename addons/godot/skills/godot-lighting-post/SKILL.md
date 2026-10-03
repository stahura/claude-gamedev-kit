---
name: godot-lighting-post
description: Godot 4 settings for the style slice's lighting-and-post stage (WorldEnvironment, Environment, CameraAttributes, sky, GI, shadows) and rendering the fixed shot set to PNG for look-and-fix (tested command). Use when building or changing the style slice's lighting, or rendering shots.
---
# Godot 4 lighting and post (style slice stage A: docs/visual-pipeline.md section 5)

Keep one `res://env/main.tres` (Environment) and one `res://env/camera.tres` (CameraAttributesPractical or
Physical), used by every scene's `WorldEnvironment` (`environment`, `camera_attributes`). Light the slice on
placeholder shapes first. The lock is a commit + tag of these files plus the slice scene; changing them later means a
full shot-set re-render and a new sign-off. Start values below are neutral; tune them against the art bible's mood
ref, not by taste. Stylized projects: optional techniques in `docs/godot/stylized-techniques.md`.

## Environment checklist
- [ ] Tone map: `tonemap_mode = TONE_MAPPER_AGX` (4.4+) or `TONE_MAPPER_FILMIC`; `tonemap_exposure` 1.0, tune
      `tonemap_white` (Filmic) to the brightest highlight.
- [ ] Sky: `background_mode = BG_SKY`, `Sky` with `PanoramaSkyMaterial` (HDRI `.exr`/`.hdr`) or
      `PhysicalSkyMaterial`; `ambient_light_source = AMBIENT_SOURCE_SKY`, `reflected_light_source =
      REFLECTION_SOURCE_SKY`; `Sky.radiance_size` 256+; `sky_rotation` to match the key light.
- [ ] AO: `ssao_enabled` (radius ~1, intensity ~2); optional `ssil_enabled` for colour bleed (Forward+).
- [ ] GI (pick one per scene type): `sdfgi_enabled` for large dynamic outdoor scenes (Forward+ only); `VoxelGI` node
      for small dynamic interiors; `LightmapGI` for static scenes and the Mobile/Compatibility renderers.
- [ ] Reflections: `ssr_enabled` (Forward+) plus `ReflectionProbe` nodes in interiors.
- [ ] Glow: `glow_enabled`, `glow_hdr_threshold` ~1.0 so only emissives and highlights bloom; `glow_intensity` low.
- [ ] Fog: `fog_enabled` (`fog_mode` exponential or depth), `fog_light_color` from the palette, `fog_density`,
      `fog_aerial_perspective` 0.3-0.7, `fog_sky_affect`; `volumetric_fog_enabled` only if the mood needs shafts.
- [ ] Grade: `adjustment_enabled`, `adjustment_brightness/contrast/saturation`, `adjustment_color_correction` (a LUT
      `Texture3D` or gradient) matched to the bible palette.

## CameraAttributes, light, project settings
- Shots must be repeatable: `CameraAttributesPractical.auto_exposure_enabled = false` (or Physical with fixed
  `exposure_*`), `exposure_multiplier` set once. No DOF in the shot set unless the bible asks for it.
- `DirectionalLight3D`: `shadow_enabled`, `directional_shadow_mode = SHADOW_PARALLEL_4_SPLITS`,
  `directional_shadow_max_distance` to the camera's useful range, `light_angular_distance` 0.5-2 for soft edges.
- Project settings: `rendering/anti_aliasing/quality/msaa_3d` 2x-4x or `use_taa` (TAA needs settle frames),
  `rendering/lights_and_shadows/directional_shadow/size` 4096, `rendering/textures/default_filters/anisotropic_filtering_level` 4x+.
- Materials: `StandardMaterial3D` with `uv1_triplanar` for environment surfaces; trim sheets on modular kit pieces;
  `Decal` nodes for wear and variation.

## Rendering the shot set
Tested with Godot 4.7.2 on Windows (Forward+, Vulkan, a GPU window opens for a few seconds; PNGs at the set's
resolution, exit 0; a missing scene or a PNG not at the set's resolution exits 1; two renders byte-identical):
```
godot_console --headless --path . --import
godot_console --path . --resolution 1280x720 --fixed-fps 60 --quit-after 3000 -s res://tools/render_shots.gd -- --out=docs/shots/_work/<run>/<phase>/i<N>
python tools/contact_sheet.py --src docs/shots/_work/<run>/<phase>/i<N> --out docs/shots/_work/<run>/<phase>/i<N>-contact.png
godot_console --path . --resolution 1920x1080 --quit-after 5000 -s res://tools/render_shots.gd -- --bench=600 > bench.log
python tools/perf_gate.py --phase P<N> bench.log
```
- Iterations go to `docs/shots/_work/` (git-ignored); the reviewed set is copied to `docs/shots/<run>/<phase>/final/`.
- `--bench=<frames>` renders no PNGs: it holds the first shot's camera (or `--bench-shot=<name>`) with vsync off and
  prints `BENCH avg_fps=<x> low1_fps=<y>`; run it without `--fixed-fps`.
- Add `--set=res://<path>.json` for another shot set and `--only=shot-01-x,shot-02-y` to re-render the shots a
  single change affects (look-and-fix before/after pairs).
- `--quit-after` counts frames: raise it above (shots x (settle_frames + 2)) for big sets; it is only a failsafe.
- Needs a GPU window (Forward+ lighting under `--headless` renders nothing reviewable). On Linux: `xvfb-run -a` only
  with a GPU-backed display.
- `settle_frames` in `shots.json` (default 30) lets TAA, SDFGI and exposure converge; raise it if shots differ
  between two renders of the same commit.
- Two renders of the same commit must look identical: the script seeds the global RNG per shot (`seed` in the set)
  and pauses the tree with `Engine.time_scale = 0` after the settle frames; `--fixed-fps 60` makes shader `TIME`
  advance identically. Scatter with its own `RandomNumberGenerator` must seed it explicitly.
