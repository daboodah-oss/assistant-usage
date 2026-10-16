#!/usr/bin/env python3
"""Write icons/icon-maskable-512.png from icons/icon-512.png.

    python3 tools/make_maskable.py

Android launchers crop app icons to a circle or squircle.  A maskable icon
keeps the mark inside the central circle of 80% diameter (the safe zone)
with the background running to the edge.  The background colour is read
from the source icon's corner; the mark is every pixel that differs from
it.  The mark is scaled so its farthest pixel from the centre lands at 38%
of the side (40% is the safe radius; the rest is antialiasing margin).

One-time tool, run by hand when the logo changes.  Needs Pillow.
"""
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
SAFE = 0.38


def maskable(src, size=512, safe=SAFE, threshold=40):
    from PIL import Image
    im = src.convert("RGB")
    n = im.size[0]
    bg = im.getpixel((0, 0))
    px = im.load()
    c = n / 2
    far = max(((x + .5 - c) ** 2 + (y + .5 - c) ** 2) ** .5
              for y in range(n) for x in range(n)
              if max(abs(a - b) for a, b in zip(px[x, y], bg)) > threshold)
    inner = int(round(n * (safe * size / far)))  # source scaled to this many px
    inner = min(inner, size)
    out = Image.new("RGB", (size, size), bg)
    out.paste(im.resize((inner, inner), Image.LANCZOS), ((size - inner) // 2, (size - inner) // 2))
    return out


def main():
    try:
        from PIL import Image
    except ImportError:
        sys.exit("make_maskable needs Pillow: pip install pillow")
    src = Image.open(ROOT / "icons" / "icon-512.png")
    maskable(src).save(ROOT / "icons" / "icon-maskable-512.png", optimize=True)
    print("wrote icons/icon-maskable-512.png")


if __name__ == "__main__":
    main()
