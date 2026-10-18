"""Draw the placeholder app icon: the compass rose from docs/public/favicon.svg.

Writes assets/icon.png (1024 px). electron-builder derives the Windows .ico and the
macOS .icns from it, and the PyInstaller spec uses it for the sidecar executable.
Drawn with Pillow (already a dependency) so no SVG renderer is needed.

Usage:
    uv run python scripts/build/make_icon.py
"""

from pathlib import Path

from PIL import Image, ImageDraw

ROOT = Path(__file__).parent.parent.parent
OUT = ROOT / "assets" / "icon.png"

SIZE = 1024
SUPERSAMPLE = 4  # drawn large, then downsampled, for anti-aliased edges
NAVY = (14, 17, 24, 255)
GOLD = (212, 168, 83, 255)
GOLD_FAINT = (212, 168, 83, 77)  # the SVG's 0.3 opacity cross


def main() -> None:
    # The SVG's 32-unit viewBox, scaled to the supersampled canvas.
    unit = SIZE * SUPERSAMPLE / 32
    canvas = Image.new("RGBA", (SIZE * SUPERSAMPLE,) * 2, (0, 0, 0, 0))
    faint = Image.new("RGBA", canvas.size, (0, 0, 0, 0))
    draw = ImageDraw.Draw(canvas)

    def circle(target: ImageDraw.ImageDraw, r: float, **kwargs) -> None:
        c = 16 * unit
        target.ellipse((c - r * unit, c - r * unit, c + r * unit, c + r * unit), **kwargs)

    def line(target: ImageDraw.ImageDraw, x1, y1, x2, y2, width: float, fill) -> None:
        target.line(
            (x1 * unit, y1 * unit, x2 * unit, y2 * unit), fill=fill, width=round(width * unit)
        )

    # Outer disc, slightly larger than the favicon's so it fills the icon tile.
    circle(draw, 15, fill=NAVY, outline=GOLD, width=round(1.0 * unit))
    faint_draw = ImageDraw.Draw(faint)
    line(faint_draw, 16, 6, 16, 26, 0.8, GOLD_FAINT)
    line(faint_draw, 6, 16, 26, 16, 0.8, GOLD_FAINT)
    canvas = Image.alpha_composite(canvas, faint)
    draw = ImageDraw.Draw(canvas)
    for x1, y1, x2, y2 in ((16, 4, 16, 8), (16, 24, 16, 28), (4, 16, 8, 16), (24, 16, 28, 16)):
        line(draw, x1, y1, x2, y2, 1.4, GOLD)
    circle(draw, 3, outline=GOLD, width=round(1.0 * unit))
    circle(draw, 1, fill=GOLD)

    OUT.parent.mkdir(parents=True, exist_ok=True)
    canvas.resize((SIZE, SIZE), Image.Resampling.LANCZOS).save(OUT, optimize=True)
    print(f"Wrote {OUT}")


if __name__ == "__main__":
    main()
