"""The README lockups and social preview: sizes, transparency, and the mark's colours."""

from scripts.build.build_brand_images import DARK, LIGHT, lockup, render_mark, social_preview


def test_social_preview_is_the_size_github_expects():
    assert social_preview().size == (1280, 640)


def test_lockup_is_wide_transparent_and_as_tall_as_the_mark_plus_padding():
    img = lockup(48, DARK, pad=4)
    assert img.mode == "RGBA"
    assert img.width > 4 * img.height
    assert img.getpixel((0, 0))[3] == 0  # type: ignore[index]
    assert img.height == round(0.85 * 48) + 8


def test_mark_uses_the_requested_page_colour():
    light = render_mark(64, LIGHT)
    dark = render_mark(64, DARK)
    # a point well inside the left page
    x, y = light.width // 4, light.height // 3
    assert light.getpixel((x, y))[:3] == (0x0E, 0x11, 0x18)  # type: ignore[index]
    assert dark.getpixel((x, y))[:3] == (0xED, 0xE8, 0xDC)  # type: ignore[index]
