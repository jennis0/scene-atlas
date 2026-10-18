"""Raster brand images for places that can't load the app's fonts: the README header and
the GitHub social preview. The mark comes from build_icons.py; the wordmark is Cinzel,
as in the app.

Usage:
    uv run python -m scripts.build.build_brand_images

Writes:
    assets/brand/lockup-dark.png     mark and wordmark for dark backgrounds, transparent
    assets/brand/lockup-light.png    mark and wordmark for light backgrounds, transparent
    assets/brand/social-preview.png  1280x640, for the repository's social preview
                                     (upload it by hand: Settings > General > Social preview)
"""

from __future__ import annotations

from dataclasses import dataclass

from PIL import Image, ImageDraw, ImageFont

from scripts.build.build_icons import GOLD, NAVY, PARCHMENT, ROOT, _bounds, mark_shapes

FONTS = ROOT / "electron" / "fonts"
WORDMARK = "Scene Atlas"
TAGLINE = "Find any map in your collection by describing it."
SUBLINE = "Free and open source  ·  Windows, macOS, Linux and self-hosted"

# Light theme colours from the Navy palette's light mode (frontend/src/index.css)
INK = "#2b2622"  # --foreground: 30 12% 15%
GOLD_ON_LIGHT = "#db9824"  # --primary: 38 72% 50%
MUTED_ON_DARK = "#9e978b"  # --muted-foreground (dark): 37 9% 58%

MARK_HEIGHT = 0.85  # of the font size, as beside the wordmark in the app
MARK_GAP = 0.45
TRACKING = 0.04  # Cinzel wordmark letter-spacing in the app


@dataclass(frozen=True)
class Colours:
    pages: str
    band: str
    text: str


DARK = Colours(pages=PARCHMENT, band=GOLD, text=PARCHMENT)
LIGHT = Colours(pages=INK, band=GOLD_ON_LIGHT, text=INK)


def _font(name: str, px: int, weight: int) -> ImageFont.FreeTypeFont:
    font = ImageFont.truetype(str(FONTS / name), px)
    font.set_variation_by_axes([weight])
    return font


def render_mark(height: int, colours: Colours, supersample: int = 8) -> Image.Image:
    """The mark alone, `height` px tall, cropped to its bounds on a transparent background."""
    shapes = mark_shapes()
    x0, y0, x1, y1 = _bounds(shapes)
    scale = height * supersample / (y1 - y0)
    size = (round((x1 - x0) * scale), height * supersample)
    img = Image.new("RGBA", size, (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)
    for s in shapes:
        fill = colours.band if s.fill == GOLD else colours.pages
        draw.polygon([((x - x0) * scale, (y - y0) * scale) for x, y in s.polygon], fill=fill)
    return img.resize((round(size[0] / supersample), height), Image.Resampling.LANCZOS)


def _tracked_width(text: str, font: ImageFont.FreeTypeFont, tracking: float) -> float:
    return font.getlength(text) + (len(text) - 1) * tracking


def _draw_tracked(
    draw: ImageDraw.ImageDraw,
    xy: tuple[float, float],
    text: str,
    font: ImageFont.FreeTypeFont,
    fill: str,
    tracking: float,
) -> None:
    """Draw text with letter-spacing, keeping the font's own kerning between letters."""
    x, y = xy
    for i, ch in enumerate(text):
        dx = font.getlength(text[:i]) + i * tracking
        draw.text((x + dx, y), ch, font=font, fill=fill, anchor="ls")


def lockup(font_px: int, colours: Colours, pad: int = 8) -> Image.Image:
    """Mark and wordmark side by side, the mark centred on the capitals, as in the app."""
    font = _font("cinzel-latin-wght.woff2", font_px, 500)
    tracking = TRACKING * font_px
    cap_height = round(-font.getbbox("H", anchor="ls")[1])
    mark = render_mark(round(MARK_HEIGHT * font_px), colours)
    gap = round(MARK_GAP * font_px)
    text_w = round(_tracked_width(WORDMARK, font, tracking))
    height = max(mark.height, cap_height) + 2 * pad
    img = Image.new("RGBA", (pad + mark.width + gap + text_w + pad, height), (0, 0, 0, 0))
    centre = height / 2
    img.alpha_composite(mark, (pad, round(centre - mark.height / 2)))
    baseline = centre + cap_height / 2
    _draw_tracked(
        ImageDraw.Draw(img),
        (pad + mark.width + gap, baseline),
        WORDMARK,
        font,
        colours.text,
        tracking,
    )
    return img


def social_preview() -> Image.Image:
    img = Image.new("RGBA", (1280, 640), NAVY)
    mark_and_name = lockup(112, DARK, pad=0)
    img.alpha_composite(mark_and_name, ((1280 - mark_and_name.width) // 2, 192))
    draw = ImageDraw.Draw(img)
    tagline = _font("figtree-latin-wght.woff2", 38, 400)
    subline = _font("figtree-latin-wght.woff2", 26, 400)
    draw.text((640, 402), TAGLINE, font=tagline, fill=PARCHMENT, anchor="ms")
    draw.text((640, 458), SUBLINE, font=subline, fill=MUTED_ON_DARK, anchor="ms")
    return img


def main() -> None:
    brand = ROOT / "assets" / "brand"
    # 2x the size the README shows them at, for high-density screens
    lockup(96, DARK).save(brand / "lockup-dark.png")
    lockup(96, LIGHT).save(brand / "lockup-light.png")
    social_preview().convert("RGB").save(brand / "social-preview.png")
    print(f"Wrote lockups and social preview to {brand.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
