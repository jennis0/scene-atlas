"""sRGB hex to CIELAB (D65) conversion.

Dependency-free so both the ORM models and the colour search can use it.
Migration 024 carries its own copy, which must stay in step with this one.
"""

_WHITE_X = 0.95047
_WHITE_Z = 1.08883
_EPSILON = 216 / 24389
_KAPPA = 24389 / 27


def _linear(channel: int) -> float:
    c = channel / 255
    return c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4


def _f(t: float) -> float:
    return t ** (1 / 3) if t > _EPSILON else (_KAPPA * t + 16) / 116


def hex_to_lab(hex_color: str) -> tuple[float, float, float]:
    """``'#rrggbb'`` (``#`` optional) to CIELAB ``(L*, a*, b*)`` under D65."""
    h = hex_color.lstrip("#")
    r, g, b = (_linear(int(h[i : i + 2], 16)) for i in (0, 2, 4))
    x = (0.4124564 * r + 0.3575761 * g + 0.1804375 * b) / _WHITE_X
    y = 0.2126729 * r + 0.7151522 * g + 0.0721750 * b
    z = (0.0193339 * r + 0.1191920 * g + 0.9503041 * b) / _WHITE_Z
    fx, fy, fz = _f(x), _f(y), _f(z)
    return (116 * fy - 16, 500 * (fx - fy), 200 * (fy - fz))
