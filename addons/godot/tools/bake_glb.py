"""Bake a uniform scale and a recentre into a plain (unrigged) Meshy GLB: the largest horizontal side becomes
`footprint` metres, the base sits at y = 0 and the footprint is centred on the origin.

Usage: python tools/bake_glb.py in.glb out.glb <footprint_m>
Works on the GLB container directly (JSON + BIN chunks, positions edited in place) so embedded textures and
buffer layouts stay byte-identical. Prints the resulting size and triangle count for the manifest.
"""
import json
import struct
import sys

import numpy as np


def main() -> int:
    src, dst, fp = sys.argv[1], sys.argv[2], float(sys.argv[3])
    data = open(src, "rb").read()
    magic, version, _ = struct.unpack_from("<III", data, 0)
    assert magic == 0x46546C67 and version == 2, "not a GLB v2"
    jlen, jtype = struct.unpack_from("<II", data, 12)
    assert jtype == 0x4E4F534A
    doc = json.loads(data[20:20 + jlen])
    off = 20 + jlen
    blen, btype = struct.unpack_from("<II", data, off)
    assert btype == 0x004E4942
    blob = bytearray(data[off + 8:off + 8 + blen])
    assert not doc.get("skins"), "rigged GLBs are not handled"
    ident = [1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1]
    for n in doc.get("nodes", []):
        assert n.get("matrix", ident) == ident and not any(k in n for k in ("translation", "rotation", "scale")), \
            "node transforms are not handled"
    acc_ids = sorted({p["attributes"]["POSITION"] for m in doc["meshes"] for p in m["primitives"]})
    accs = doc["accessors"]
    mins = np.min([accs[a]["min"] for a in acc_ids], 0)
    maxs = np.max([accs[a]["max"] for a in acc_ids], 0)
    size = maxs - mins
    f = fp / max(size[0], size[2])
    shift = np.array([-(mins[0] + maxs[0]) / 2, -mins[1], -(mins[2] + maxs[2]) / 2])
    for ai in acc_ids:
        a = accs[ai]
        bv = doc["bufferViews"][a["bufferView"]]
        assert a["componentType"] == 5126 and a["type"] == "VEC3" and "sparse" not in a
        assert bv.get("byteStride", 12) == 12, "interleaved buffers are not handled"
        o = bv.get("byteOffset", 0) + a.get("byteOffset", 0)
        arr = np.frombuffer(bytes(blob[o:o + a["count"] * 12]), dtype="<f4").reshape(-1, 3)
        arr = ((arr + shift) * f).astype("<f4")
        blob[o:o + arr.nbytes] = arr.tobytes()
        a["min"] = [float(v) for v in arr.min(0)]
        a["max"] = [float(v) for v in arr.max(0)]
    js = json.dumps(doc, separators=(",", ":")).encode()
    js += b" " * ((4 - len(js) % 4) % 4)
    blob += b"\0" * ((4 - len(blob) % 4) % 4)
    total = 12 + 8 + len(js) + 8 + len(blob)
    with open(dst, "wb") as out:
        out.write(struct.pack("<III", 0x46546C67, 2, total))
        out.write(struct.pack("<II", len(js), 0x4E4F534A) + js)
        out.write(struct.pack("<II", len(blob), 0x004E4942) + bytes(blob))
    tris = sum(accs[p["indices"]]["count"] // 3 for m in doc["meshes"] for p in m["primitives"])
    print(f"baked x{f:.4f} -> {dst}: size {size[0] * f:.3f} x {size[1] * f:.3f} x {size[2] * f:.3f} m, {tris} tris")
    return 0


if __name__ == "__main__":
    sys.exit(main())
