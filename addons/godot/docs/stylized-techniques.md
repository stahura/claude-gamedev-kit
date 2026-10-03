# Stylized techniques (Godot 4): reference, not rules

**Techniques, not rules. For stylized projects only.** The art bible and the style lock decide; use these only where
they serve the bible, and drop any that the visual-reviewer scores down. Realistic projects: ignore this file.

## Vegetation
- **Sphere-normal canopies:** build canopies as clumps of alpha-cut leaf cards, wrap each clump (or the whole canopy)
  in a smooth ellipsoid and transfer its normals onto the cards (Blender Data Transfer modifier, custom split
  normals). The canopy shades as soft volumes instead of flickering planes.
- **Vertex-colour channels** baked in Blender for the shader: R = height in the plant (0 base, 1 top), G = distance
  from trunk/stem (wind strength), B = random per clump (hue variation, wind phase).
- **Shared global wind:** Project Settings > Shader Globals `wind_direction` (vec3), `wind_strength`, `wind_speed`;
  every foliage, grass, particle and fog shader reads them (`global uniform`), so everything moves with one wind.
  Vertex shader: slow whole-plant sway from the base plus faster flutter scaled by G and offset by B.
- **Foliage backlight / translucency:** in the fragment shader, add a warm term when the key light is behind the
  leaves relative to the camera (`BACKLIGHT` in a spatial shader, or `dot(VIEW, LIGHT)` in `light()`); colour from a
  gradient driven by R (tops lit warm, undersides cool).
- Alpha scissor (cutout), not blend, for leaves and grass: correct sorting and shadows.
- **MultiMesh grass:** clumps of 3-6 blades or cards in `MultiMeshInstance3D`, placed from a density mask (thin on
  paths, under rocks); base colour matches the ground, tip brighter; per-instance hue variation
  (`INSTANCE_CUSTOM`); `visibility_range_end` fade so the ground texture takes over at distance.
- Place in clusters and compositions (framing, clearings, dense edges), never uniform random scatter.

## Ground and rocks
- **Triplanar rocks with moss:** `uv1_triplanar` or a custom triplanar shader with a painted texture, a lighter
  top-facing tint and moss on upward faces from the world-space normal (`smoothstep` on `NORMAL.y` in world space).
  Every rock then matches the scene automatically.
- Terrain: 3-4 painted layers blended by splat map or vertex colour, triplanar on steep slopes, large-scale colour
  noise so the ground is never one flat tone; its grass layer colour equals the grass blade base colour.

## Atmosphere and light
- **Fog volumes:** `FogVolume` nodes (box or ellipsoid) with a `FogMaterial` or a fog shader with animated noise for
  local mist pockets; needs `volumetric_fog_enabled`. Raise `DirectionalLight3D.light_volumetric_fog_energy` above 1
  for visible light shafts; `volumetric_fog_anisotropy` 0.3-0.6 scatters toward the camera when facing the sun.
- **Time-of-day presets:** one `Resource` per preset (sun angle and colour, ambient tint, fog colour and density,
  exposure, sky) and a controller that blends between them; capture the shot set at the hero preset plus one other.
- **Particles:** `GPUParticles3D` for dust in light shafts, falling leaves, emissive fireflies (they should bloom),
  drifting seeds; modest counts, `visibility_range_end`, all driven by the shared wind.
- Cheap life: drifting cloud shadows from a world-space XZ noise texture scrolled by time and the shared wind,
  multiplied into ground and foliage shading (`light_projector` works on omni and spot lights only, not the sun).
