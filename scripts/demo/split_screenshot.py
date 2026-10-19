"""Combine the dark and light captures into one image split along a diagonal.

Dark on the left, light on the right, with a thin gold line along the seam. Both captures
must be the same size (screenshots.mjs takes them with identical layouts).

Usage:
    uv run python -m scripts.demo.split_screenshot <dark.png> <light.png> <out.webp>
"""

from __future__ import annotations

import sys

from PIL import Image, ImageDraw

GOLD = "#dda43c"  # the Navy palette's accent
# Where the seam meets the top and bottom edges, as a share of the width
TOP_X = 0.58
BOTTOM_X = 0.42
LINE = 3
SUPERSAMPLE = 4  # draw the mask large and scale down, for a smooth edge


def split(dark: Image.Image, light: Image.Image) -> Image.Image:
    if dark.size != light.size:
        raise ValueError(f"captures differ in size: {dark.size} vs {light.size}")
    w, h = dark.size
    top, bottom = TOP_X * w, BOTTOM_X * w

    big = (w * SUPERSAMPLE, h * SUPERSAMPLE)
    mask = Image.new("L", big, 0)
    s = SUPERSAMPLE
    ImageDraw.Draw(mask).polygon(
        [(top * s, 0), (big[0], 0), (big[0], big[1]), (bottom * s, big[1])], fill=255
    )
    mask = mask.resize((w, h), Image.Resampling.LANCZOS)

    out = Image.composite(light.convert("RGB"), dark.convert("RGB"), mask)
    seam = Image.new("RGBA", big, (0, 0, 0, 0))
    ImageDraw.Draw(seam).line([(top * s, 0), (bottom * s, big[1])], fill=GOLD, width=LINE * s)
    seam = seam.resize((w, h), Image.Resampling.LANCZOS)
    out.paste(seam, (0, 0), seam)
    return out


def main() -> None:
    dark, light, out = sys.argv[1:4]
    split(Image.open(dark), Image.open(light)).save(out, "WEBP", quality=88, method=6)


if __name__ == "__main__":
    main()
