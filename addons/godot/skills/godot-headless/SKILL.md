---
name: godot-headless
description: Building, testing, screenshotting and exporting a Godot 4 project from an unattended Claude Code run on Windows or Linux - commands, the smoke-runner output contract, screenshots and contact sheets, export/release, and the traps that cost retries in past runs.
---
# Godot headless (Godot 4.x, GDScript)

## Commands
- Windows: run Godot from the **PowerShell tool** with the console binary (`godot_console` / `Godot_*_console.exe`);
  the GUI `.exe` detaches immediately and scripted runs race ahead. Git Bash cannot run `.cmd` shims.
- Linux: `godot --headless ...`; screenshots need a display: `xvfb-run -a godot --path . ...` (software GL is slow and
  is not good enough to judge Forward+ lighting: do visual review on a GPU machine).
- `godot --headless --path . --import` after adding any file, and after adding a script with a new `class_name`
  (scripts using it fail to parse until the global class cache is rebuilt).
- Smoke: `godot --headless --path . --fixed-fps 60 -s res://tests/_harness/smoke_runner.gd -- --scenarios=a,b --watchdog=180`.
  Contract: `SCENARIO <name> OK checks=<n>` per pass, `SMOKE FAIL: <name>: <why>` on failure, `SMOKE DONE` at the end.
  Install a `Logger` (`OS.add_logger`) in the runner that fails a scenario on any SCRIPT ERROR: a GDScript runtime error
  aborts `run()` silently and the scenario would otherwise pass.
- Screenshots: a `-- --shots` CLI in the game that poses fixed camera beats, saves `user://shots/beat-N-name.png` and
  quits, with a frame failsafe; always pass `--quit-after <frames>` too (if the main script fails to compile the CLI
  never starts). Contact sheet: `python tools/contact_sheet.py --out docs/shots/<run>/pN.png`.
- Look-and-fix shot set (`docs/shots/shots.json`): `tools/render_shots.gd`; lighting/post settings: the
  `godot-lighting-post` skill.
- Export: `godot --headless --path . --export-release "<preset>" build/<platform>/<name>.exe`, then zip and
  `gh release upload <run>-build <zip> --clobber`. Exclude `tests/*,docs/*,tools/*` and concept art in the preset.

## Traps (each cost a retry)
- Typed GDScript: `var x := obj.member` fails to parse when `obj` is untyped ("Cannot infer the type"). Write
  `var x: float = obj.member`. Grep for `:= .*\bm\.` (or your module handle) before running.
- Lambdas capture locals by value: keep mutable state in an array (`var last := [""]`).
- `get_tree().paused` stops `_process`/`_physics_process`/input on paused nodes: dialogue, camera, HUD, audio and any
  ticker that must run during cutscenes need `process_mode = PROCESS_MODE_ALWAYS`; reset `paused` between test scenarios.
- The headless test viewport is tiny (64x64 by default): HUD controls must not swallow clicks (mouse_filter IGNORE,
  route clicks by rect, hide under ~480 px wide), or box select breaks in tests. Test the HUD at a real size too by
  setting `get_tree().root.size` in the scenario.
- Meshy rigged GLBs come pre-scaled by the rig's height; clip GLBs carry the whole mesh: set
  `import_script/path="res://tools/strip_meshes_import.gd"` and `gltf/embedded_image_handling=0` in clip `.import` files.
  Strip hips root motion at load for in-place clips. Cap 2k textures with `process/size_limit=1024`.
- Static GLB rescale/recentre without Blender: `tools/bake_glb.py` (edits the GLB container; pygltflib's save corrupts
  embedded images).
- Navigation: bake at runtime from procedural faces (`add_faces`), not from visual meshes; ~20 ms for a 240x320 m map.
- Performance check: `render_shots.gd -- --bench=<frames>` (or a game `--bench` flythrough) printing
  `BENCH avg_fps=<x> low1_fps=<y>` at the target resolution; `python tools/perf_gate.py --phase P<N> <log>` checks it
  against kit.json `visual.perf`.
