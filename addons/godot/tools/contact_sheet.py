"""Tile the --shots PNGs into one labelled contact sheet.

Usage: python tools/contact_sheet.py [--src DIR] [--out docs/art/run2/p2-contact.png] [--cols 3] [--width 640]
Default source: user://shots of the Godot project in the current directory.
"""
import argparse
import os
import re
import sys

from PIL import Image, ImageDraw, ImageFont

def _default_src() -> str:
    """user://shots of the Godot project in the current directory (Windows APPDATA or Linux ~/.local/share)."""
    name = "Godot Project"
    try:
        for line in open("project.godot", encoding="utf-8"):
            if line.startswith("config/name="):
                name = line.split("=", 1)[1].strip().strip('"')
    except OSError:
        pass
    base = os.environ.get("APPDATA") or os.path.join(os.path.expanduser("~"), ".local", "share")
    return os.path.join(base, "Godot", "app_userdata", name, "shots")


DEFAULT_SRC = _default_src()


def _order(name: str):
    m = re.match(r"(?:beat|shot)-(\d+)-", name)
    return (int(m.group(1)) if m else 9999, name)


def _font(size: int):
    for f in ("arialbd.ttf", "arial.ttf", "DejaVuSans-Bold.ttf"):
        try:
            return ImageFont.truetype(f, size)
        except OSError:
            continue
    return ImageFont.load_default()


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--src", default=DEFAULT_SRC)
    ap.add_argument("--out", default="docs/shots/contact.png")
    ap.add_argument("--cols", type=int, default=3)
    ap.add_argument("--width", type=int, default=640, help="tile width in px")
    ap.add_argument("--title", default="")
    a = ap.parse_args()
    files = sorted((f for f in os.listdir(a.src) if f.lower().endswith(".png")), key=_order)
    if not files:
        print(f"no PNGs in {a.src}", file=sys.stderr)
        return 1
    tiles = []
    for f in files:
        im = Image.open(os.path.join(a.src, f)).convert("RGB")
        h = round(im.height * a.width / im.width)
        tiles.append((f, im.resize((a.width, h), Image.LANCZOS)))
    label_h = 30
    title_h = 40 if a.title else 0
    cols = min(a.cols, len(tiles))
    rows = (len(tiles) + cols - 1) // cols
    th = max(t.height for _, t in tiles)
    sheet = Image.new("RGB", (cols * a.width + (cols + 1) * 6, title_h + rows * (th + label_h) + (rows + 1) * 6), (24, 22, 20))
    d = ImageDraw.Draw(sheet)
    font = _font(18)
    if a.title:
        d.text((10, 8), a.title, fill=(240, 220, 170), font=_font(24))
    for i, (name, im) in enumerate(tiles):
        r, c = divmod(i, cols)
        x = 6 + c * (a.width + 6)
        y = title_h + 6 + r * (th + label_h + 6)
        d.text((x + 4, y + 5), os.path.splitext(name)[0], fill=(240, 230, 210), font=font)
        sheet.paste(im, (x, y + label_h))
    os.makedirs(os.path.dirname(os.path.abspath(a.out)), exist_ok=True)
    sheet.save(a.out)
    print(f"contact sheet: {a.out} ({len(tiles)} shots, {sheet.width}x{sheet.height})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
