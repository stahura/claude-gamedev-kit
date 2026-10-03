"""Headless cleanup of one generated or bought asset: scale + pivot, clean, decimate to budget, UVs, rebake, grade
(strip baked lighting, push toward the art bible palette and value range), LODs, GLB.

  blender -b -P tools/blender/cleanup_asset.py -- --in raw.glb --out assets/x/x.glb --height 1.8 --tris 20000
      --bible ART-BIBLE.md [--footprint M] [--pivot base|center] [--lods 0.5,0.25] [--tex 2048] [--no-bake]
      [--merge 0.0001] [--palette "#rrggbb,#rrggbb"] [--value-range 30,235] [--push 0.35] [--delight 0.7] [--no-grade]

Stdlib + bpy + numpy (bundled with Blender). Tested with Blender 5.2 on Windows (static GLB with an image texture);
not yet tested on rigged assets or FBX/OBJ input.
- Scale: --height sets the bounding-box height (m) or --footprint the larger horizontal side; +Z up in Blender is
  written as +Y up by the glTF exporter. Pivot: base centre (default) or bounding-box centre, at the origin.
- Static assets: meshes joined into one. Rigged assets (an armature present): not joined; decimated per mesh; the
  rebake only runs when there is a single mesh.
- Rebake: the cleaned, decimated mesh gets fresh smart-project UVs and base colour + normal maps baked from the
  original (Cycles, selected to active). --no-bake keeps the original UVs and materials.
- Grade (every base-colour texture, mandatory for AI-generated assets): divides out low-frequency luminance (baked-in
  light and shadow) by --delight, clamps value to the bible's albedo range, and moves each texel's colour toward the
  nearest bible palette colour by --push, keeping its value. --bible reads the `#rrggbb` codes and the "Albedo value
  range" numbers from its `## Palette` section; --palette and --value-range override it.
- Meshes with shape keys cannot take the Decimate modifier: remove the keys first or pass --tris 0.
- LODs: one GLB per ratio of LOD0's triangles, named <out>_LOD1.glb, ...
Prints one line: CLEANUP {"out": ..., "size_m": [x, y, z], "tris": [lod0, lod1, ...], "graded": [...]}
"""
import json
import math
import os
import re
import sys

import bpy
import numpy as np
from mathutils import Vector


def args() -> dict:
    argv = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else []
    a = {"in": "", "out": "", "height": 0.0, "footprint": 0.0, "tris": 0, "pivot": "base", "lods": "0.5,0.25",
         "tex": 2048, "bake": True, "merge": 0.0001, "bible": "", "palette": "", "value-range": "", "push": 0.35,
         "delight": 0.7, "grade": True}
    i = 0
    while i < len(argv):
        k = argv[i].lstrip("-")
        if k in ("no-bake", "no-grade"):
            a[k[3:]] = False
        else:
            i += 1
            v = argv[i]
            a[k] = type(a[k])(v) if k in a and not isinstance(a[k], bool) else v
        i += 1
    if not a["in"] or not a["out"]:
        sys.exit("usage: blender -b -P cleanup_asset.py -- --in raw.glb --out x.glb [--height M | --footprint M] ...")
    return a


def bible_grade(a: dict) -> tuple:
    """Palette (list of 0-1 RGB) and value range (0-1 pair or None) from --palette/--value-range or the bible."""
    text = ""
    if a["bible"]:
        doc = open(a["bible"], encoding="utf-8").read()
        m = re.search(r"^## Palette\n(.*?)(?=^## |\Z)", doc, re.S | re.M)
        text = re.sub(r"<!--.*?-->", "", m.group(1), flags=re.S) if m else ""
    hexes = re.findall(r"#([0-9a-fA-F]{6})\b", a["palette"] or text)
    pal = [[int(h[i:i + 2], 16) / 255 for i in (0, 2, 4)] for h in hexes]
    vr = a["value-range"]
    if not vr:
        line = next((ln for ln in text.splitlines() if "value range" in ln.lower()), "")
        vr = ",".join(re.findall(r"\b(\d{1,3})\b", line.split(":", 1)[-1])[:2])
    nums = [int(x) / 255 for x in vr.split(",") if x.strip()] if vr else []
    return pal, (tuple(nums) if len(nums) == 2 and nums[0] < nums[1] else None)


def blur(x, r: int):
    """Box blur of a 2-D array with radius r (edge-padded), via cumulative sums, two passes."""
    for _ in range(2):
        for ax in (0, 1):
            p = np.pad(x, [(r + 1, r) if i == ax else (0, 0) for i in range(2)], mode="edge")
            c = np.cumsum(p, axis=ax)
            x = (np.take(c, range(2 * r + 1, c.shape[ax]), axis=ax) -
                 np.take(c, range(0, c.shape[ax] - 2 * r - 1), axis=ax)) / (2 * r + 1)
    return x


def grade(img, pal: list, vrange, push: float, delight: float) -> None:
    w, h = img.size
    if w * h == 0:
        return
    px = np.empty(w * h * 4, dtype=np.float32)
    img.pixels.foreach_get(px)
    px = px.reshape(h, w, 4)
    rgb = px[:, :, :3].astype(np.float64)
    cover = (px[:, :, 3] > 0.5).astype(np.float64)  # texels the UVs use (bakes start transparent)
    if not cover.any():
        return
    if delight > 0:
        lum = rgb @ np.array([0.2126, 0.7152, 0.0722])
        r = max(1, min(w, h) // 8)
        low = np.maximum(blur(lum * cover, r) / np.maximum(blur(cover, r), 1e-6), 1e-3)
        mean = (lum * cover).sum() / cover.sum()
        rgb = rgb * ((mean / low) ** delight)[:, :, None]
    val = np.maximum(rgb.max(axis=2, keepdims=True), 1e-4)
    if vrange:
        rgb = rgb * np.clip(val, vrange[0], vrange[1]) / val
        val = np.maximum(rgb.max(axis=2, keepdims=True), 1e-4)
    if pal and push > 0:
        p = np.array(pal)
        pn = p / np.maximum(p.max(axis=1, keepdims=True), 1e-4)
        near = p[np.argmin((((rgb / val)[:, :, None, :] - pn[None, None]) ** 2).sum(axis=3), axis=2)]
        lw = np.array([0.2126, 0.7152, 0.0722])
        target = near * ((rgb @ lw) / np.maximum(near @ lw, 1e-4))[:, :, None]  # palette hue, texel luminance
        rgb = rgb + push * (target - rgb)
    px[:, :, :3] = np.where(cover[:, :, None] > 0, np.clip(rgb, 0, 1), px[:, :, :3])
    img.pixels.foreach_set(px.ravel())
    img.update()


def base_colour_images(objs: list) -> list:
    seen = []
    for o in objs:
        for slot in o.material_slots:
            m = slot.material
            if not m or not m.node_tree:
                continue
            for n in m.node_tree.nodes:
                if n.type == "BSDF_PRINCIPLED":
                    for link in n.inputs["Base Color"].links:
                        img = getattr(link.from_node, "image", None)
                        if img is not None and img not in seen:
                            seen.append(img)
    return seen


def load(path: str) -> None:
    for o in list(bpy.data.objects):
        bpy.data.objects.remove(o, do_unlink=True)
    ext = os.path.splitext(path)[1].lower()
    if ext in (".glb", ".gltf"):
        bpy.ops.import_scene.gltf(filepath=path)
    elif ext == ".fbx":
        bpy.ops.import_scene.fbx(filepath=path)
    elif ext == ".obj":
        bpy.ops.wm.obj_import(filepath=path)
    else:
        sys.exit("unsupported input: " + ext)


def meshes() -> list:
    return [o for o in bpy.context.scene.objects if o.type == "MESH"]


def select(objs: list, active=None) -> None:
    bpy.ops.object.select_all(action="DESELECT")
    for o in objs:
        o.select_set(True)
    bpy.context.view_layer.objects.active = active or (objs[0] if objs else None)


def bbox(objs: list):
    pts = [o.matrix_world @ Vector(c) for o in objs for c in o.bound_box]
    lo = Vector((min(p.x for p in pts), min(p.y for p in pts), min(p.z for p in pts)))
    hi = Vector((max(p.x for p in pts), max(p.y for p in pts), max(p.z for p in pts)))
    return lo, hi


def tris(objs: list) -> int:
    dg = bpy.context.evaluated_depsgraph_get()
    n = 0
    for o in objs:
        m = o.evaluated_get(dg).to_mesh()
        m.calc_loop_triangles()
        n += len(m.loop_triangles)
        o.evaluated_get(dg).to_mesh_clear()
    return n


def normalize(a: dict) -> None:
    """Uniform scale to --height/--footprint and pivot at the origin, applied to the root objects, then baked in."""
    objs = meshes()
    lo, hi = bbox(objs)
    size = hi - lo
    f = 1.0
    if a["height"] > 0 and size.z > 0:
        f = a["height"] / size.z
    elif a["footprint"] > 0 and max(size.x, size.y) > 0:
        f = a["footprint"] / max(size.x, size.y)
    pivot = Vector(((lo.x + hi.x) / 2, (lo.y + hi.y) / 2, lo.z if a["pivot"] == "base" else (lo.z + hi.z) / 2))
    for o in [o for o in bpy.context.scene.objects if o.parent is None]:
        o.location = (o.location - pivot) * f
        o.scale = o.scale * f
    bpy.context.view_layer.update()
    select([o for o in bpy.context.scene.objects if o.type in ("MESH", "ARMATURE")])
    bpy.ops.object.transform_apply(location=True, rotation=True, scale=True)


def clean(o, merge: float) -> None:
    select([o])
    bpy.ops.object.mode_set(mode="EDIT")
    bpy.ops.mesh.select_all(action="SELECT")
    bpy.ops.mesh.remove_doubles(threshold=merge)
    bpy.ops.mesh.delete_loose()
    bpy.ops.mesh.normals_make_consistent(inside=False)
    bpy.ops.object.mode_set(mode="OBJECT")


def decimate(o, target: int) -> None:
    have = tris([o])
    if target <= 0 or have <= target:
        return
    mod = o.modifiers.new("budget", "DECIMATE")
    mod.ratio = max(0.001, target / have)
    select([o])
    bpy.ops.object.modifier_move_to_index(modifier=mod.name, index=0)  # before any Armature modifier
    bpy.ops.object.modifier_apply(modifier=mod.name)


def bake(low, high, tex: int, out_dir: str, name: str) -> dict:
    sc = bpy.context.scene
    sc.render.engine = "CYCLES"
    sc.cycles.device = "CPU"
    sc.cycles.samples = 16
    select([low])
    bpy.ops.object.mode_set(mode="EDIT")
    bpy.ops.mesh.select_all(action="SELECT")
    bpy.ops.uv.smart_project(angle_limit=math.radians(66), island_margin=0.01)
    bpy.ops.object.mode_set(mode="OBJECT")
    mat = bpy.data.materials.new(name + "_baked")
    if mat.node_tree is None:  # Blender 4.x; 5.x always has nodes
        mat.use_nodes = True
    nt = mat.node_tree
    bsdf = next(n for n in nt.nodes if n.type == "BSDF_PRINCIPLED")
    images = {}
    for kind, space in (("color", "sRGB"), ("normal", "Non-Color")):
        img = bpy.data.images.new("%s_%s" % (name, kind), tex, tex, alpha=True)
        img.generated_color = (0, 0, 0, 0)
        img.colorspace_settings.name = space
        node = nt.nodes.new("ShaderNodeTexImage")
        node.image = img
        images[kind] = (img, node)
    low.data.materials.clear()
    low.data.materials.append(mat)
    lo, hi = bbox([high])
    extrusion = max((hi - lo).length * 0.01, 0.001)
    for kind, bake_type, extra in (("color", "DIFFUSE", {"pass_filter": {"COLOR"}}), ("normal", "NORMAL", {})):
        img, node = images[kind]
        nt.nodes.active = node
        select([high, low], active=low)
        bpy.ops.object.bake(type=bake_type, use_selected_to_active=True, cage_extrusion=extrusion, margin=8, **extra)
    nt.links.new(images["color"][1].outputs["Color"], bsdf.inputs["Base Color"])
    nmap = nt.nodes.new("ShaderNodeNormalMap")
    nt.links.new(images["normal"][1].outputs["Color"], nmap.inputs["Color"])
    nt.links.new(nmap.outputs["Normal"], bsdf.inputs["Normal"])
    return {kind: v[0] for kind, v in images.items()}


def save_images(baked: dict, out_dir: str, name: str) -> None:
    """Baked maps go next to the GLB as PNGs (the GLB embeds its own copy)."""
    for kind, img in baked.items():
        img.filepath_raw = os.path.join(out_dir, "%s_%s.png" % (name, kind))
        img.file_format = "PNG"
        img.save()


def export(objs: list, path: str) -> None:
    keep = objs + [o for o in bpy.context.scene.objects if o.type == "ARMATURE"]
    select(keep)
    bpy.ops.export_scene.gltf(filepath=path, export_format="GLB", use_selection=True, export_apply=True)


def main() -> None:
    a = args()
    load(a["in"])
    out_dir = os.path.dirname(os.path.abspath(a["out"]))
    os.makedirs(out_dir, exist_ok=True)
    name = os.path.splitext(os.path.basename(a["out"]))[0]
    rigged = any(o.type == "ARMATURE" for o in bpy.context.scene.objects)
    normalize(a)
    objs = meshes()
    if not rigged and len(objs) > 1:
        select(objs)
        bpy.ops.object.join()
        objs = meshes()
    high = None
    if a["bake"] and len(objs) == 1:
        select(objs)
        bpy.ops.object.duplicate()
        high = objs[0]
        objs = [bpy.context.view_layer.objects.active]
        objs[0].name = name
    total = tris(objs)
    for o in objs:
        clean(o, a["merge"])
        if a["tris"] > 0 and total > 0:
            decimate(o, int(a["tris"] * tris([o]) / total))
    baked = {}
    if high is not None:
        baked = bake(objs[0], high, a["tex"], out_dir, name)
        bpy.data.objects.remove(high, do_unlink=True)
    graded = []
    if a["grade"]:
        pal, vrange = bible_grade(a)
        for img in base_colour_images(objs):
            grade(img, pal, vrange, a["push"], a["delight"])
            if img not in baked.values():
                img.pack()
            graded.append(img.name)
        graded = graded or ["none: no base-colour texture"]
        if not pal:
            graded.append("warning: no palette (pass --bible or --palette)")
    save_images(baked, out_dir, name)
    export(objs, a["out"])
    counts = [tris(objs)]
    lod0 = counts[0]
    for i, r in enumerate([float(x) for x in a["lods"].split(",") if x.strip()], 1):
        now = max(1, tris(objs))
        for o in objs:
            decimate(o, int(tris([o]) * r * lod0 / now))
        path = os.path.join(out_dir, "%s_LOD%d.glb" % (name, i))
        export(objs, path)
        counts.append(tris(objs))
    lo, hi = bbox(objs)
    print("CLEANUP " + json.dumps({"out": a["out"], "size_m": [round(v, 3) for v in (hi - lo)], "tris": counts,
                                   "graded": graded}))


main()
