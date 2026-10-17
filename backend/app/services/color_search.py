"""Colour proximity search: CIE76 delta E over the precomputed LAB columns."""

from collections.abc import Sequence

from sqlalchemy import ColumnElement, Select, and_, or_, select
from sqlalchemy.orm import Session

from ..colorspace import hex_to_lab
from ..models import Color


def _within(lab: tuple[float, float, float], threshold: float) -> ColumnElement[bool]:
    lab_l, lab_a, lab_b = lab
    return and_(
        Color.lab_a.between(lab_a - threshold, lab_a + threshold),
        Color.lab_b.between(lab_b - threshold, lab_b + threshold),
        (Color.lab_l - lab_l) * (Color.lab_l - lab_l)
        + (Color.lab_a - lab_a) * (Color.lab_a - lab_a)
        + (Color.lab_b - lab_b) * (Color.lab_b - lab_b)
        <= threshold * threshold,
    )


def color_match_ids(target_hexes: Sequence[str], threshold: float) -> Select[int]:
    """Ids of images with a dominant colour within ``threshold`` delta E of ANY target.

    Each scan is a range on L* in ``ix_colors_lab``; the a*/b* box and exact
    distance are then checked from the index alone. Targets whose L* ranges overlap share one
    scan: scanning each separately would visit the shared rows once per
    target and then deduplicate them.
    """
    labs = sorted(hex_to_lab(h) for h in target_hexes)
    scans: list[list[tuple[float, float, float]]] = []
    for lab in labs:
        if scans and lab[0] - scans[-1][-1][0] <= 2 * threshold:
            scans[-1].append(lab)
        else:
            scans.append([lab])
    return select(Color.image_id).where(
        or_(
            *(
                and_(
                    Color.lab_l.between(scan[0][0] - threshold, scan[-1][0] + threshold),
                    or_(*(_within(lab, threshold) for lab in scan)),
                )
                for scan in scans
            )
        )
    )


def find_images_by_colors(
    db: Session, target_hexes: Sequence[str], threshold: float | None = None
) -> set[int]:
    """Ids of images matching ANY target colour; the threshold defaults to the app setting."""
    if not target_hexes:
        return set()
    if threshold is None:
        from .app_settings import get_settings

        threshold = get_settings(db).color_distance_threshold
    return set(db.scalars(color_match_ids(target_hexes, threshold).distinct()))
