## Godot gotchas (from the godot addon; see the godot-headless skill)
- Run Godot from PowerShell with the console binary on Windows; `--import` after new files or new `class_name` scripts.
- `var x := untyped.member` does not parse: give it an explicit type.
- Pass `--quit-after <frames>` to every scripted visual run.
- Shot-set renders need fixed exposure (auto exposure off) and enough `settle_frames`, or iterations are not comparable.
- Pass `--audio-driver Dummy` to headless renders: ALSA `ERROR:` lines otherwise fail log-based GPU checks.
- A `global uniform sampler2D` may ignore its filter hint (seen on Mesa lavapipe): magnified noise shows square texel
  blocks. Sample procedural noise through a manual bilinear/trilinear helper (texelFetch + smooth weights, mip from
  `dFdx/dFdy * textureSize`).
- Unshaded materials under AgX at exposure ~0.7: a 0.9 "white" lands near mid-grey; give intended whites an energy
  above 1 and measure the pixel.
- Godot's built-in SSR does not apply to transparent materials (water, glass): reflections there must be done in the
  shader (painted sky lookup, screen-space march) or with a planar `SubViewport` camera.
