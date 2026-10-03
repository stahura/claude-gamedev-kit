## Godot gotchas (from the godot addon; see the godot-headless skill)
- Run Godot from PowerShell with the console binary on Windows; `--import` after new files or new `class_name` scripts.
- `var x := untyped.member` does not parse: give it an explicit type.
- Pass `--quit-after <frames>` to every scripted visual run.
- Shot-set renders need fixed exposure (auto exposure off) and enough `settle_frames`, or iterations are not comparable.
