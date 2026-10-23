"""Synthetic content features and helpers for the variant-grouping tests.

Features are built so the walk's signals behave like real ones, with wide margins:

- a **layout** (one drawn map) has a random edge map and a random direction in embedding space;
  its **variants** (night, snow, ...) keep the layout (edge correlation ~0.95) and stay close in
  embedding space, so they agree (a3);
- a **rendition** (grid / no grid / VTT export of one variant) shares the variant's pHash up to a
  few bits, and its aspect;
- layouts drawn as parts of one location share a **theme**: their embeddings are dominated by
  the theme vector, so units are cohesive (~0.9) but their edge maps are unrelated. Layouts with
  different themes are nearly orthogonal (cohesion ~0).
"""

from __future__ import annotations

import hashlib
import math
from dataclasses import dataclass

import numpy as np

from backend.app.services.image_parser import ImageParser
from backend.app.services.variant_grouping import (
    ContentFeatures,
    EmbeddingThresholds,
    Grouping,
    GroupingFile,
    GroupingParams,
    group_by_paths,
    group_with_content,
)

EMBED_DIM = 64
EDGE_DIM = 1024
# Embedding mix: theme dominates (cohesion of a location's parts ~0.9), layout separates maps.
THEME_WEIGHT = 0.95
LAYOUT_WEIGHT = 0.30
VARIANT_NOISE = 0.10
EDGE_NOISE = 0.30
RENDITION_FLIPS = 3  # pHash bits a grid overlay or a re-export changes

CONTENT_PARAMS = GroupingParams(embedding=EmbeddingThresholds())


def _rng(*parts: object) -> np.random.Generator:
    """A generator seeded from ``parts`` (stable across runs and platforms)."""
    digest = hashlib.sha256(repr(parts).encode()).digest()
    return np.random.default_rng(int.from_bytes(digest[:8], "little"))


def _unit(v: np.ndarray) -> np.ndarray:
    return v / np.linalg.norm(v)


@dataclass(frozen=True)
class Look:
    """What a file depicts: a layout of a themed location, a variant of it, a rendition."""

    layout: str
    theme: str | None = None  # defaults to the layout's own theme (an unrelated map)
    variant: int = 0
    rendition: int = 0
    aspect: float = 1.0
    pixels: tuple[int, int] | None = None  # the canvas; sets the aspect when given


def features(look: Look) -> ContentFeatures:
    """Synthetic content features for one file."""
    theme = _unit(_rng("theme", look.theme or look.layout).normal(size=EMBED_DIM))
    layout = _unit(_rng("layout", look.layout).normal(size=EMBED_DIM))
    variant_noise = _rng("variant", look.layout, look.variant).normal(size=EMBED_DIM)
    embedding = _unit(
        THEME_WEIGHT * theme
        + LAYOUT_WEIGHT * layout
        + VARIANT_NOISE * _unit(variant_noise) * (look.variant > 0)
    )
    edge = _rng("edge", look.layout).normal(size=EDGE_DIM)
    if look.variant:
        edge = edge + EDGE_NOISE * _rng("edge", look.layout, look.variant).normal(size=EDGE_DIM)
    edge = (edge - edge.mean()) / edge.std()  # z-scored, as stored
    bits = _rng("phash", look.layout, look.variant).integers(0, 2, size=256).astype(np.uint8)
    flips = _rng("flip", look.layout, look.variant, look.rendition).choice(
        256, size=RENDITION_FLIPS * (look.rendition > 0), replace=False
    )
    bits[flips] ^= 1
    return ContentFeatures(
        phash256=np.packbits(bits).tobytes(),
        edge=edge.astype(np.float16),
        log_aspect=math.log(look.pixels[0] / look.pixels[1] if look.pixels else look.aspect),
        embedding=embedding.astype(np.float32),
        pixels=look.pixels,
    )


@dataclass
class Scenario:
    """Files (path -> what they depict) and the expected partition with content."""

    files: dict[str, Look]

    def grouping_files(self) -> list[GroupingFile[str]]:
        return [GroupingFile(path, path) for path in self.files]

    def content(self) -> dict[str, ContentFeatures]:
        return {path: features(look) for path, look in self.files.items()}


def parser() -> ImageParser:
    return ImageParser()


def run_paths(
    files: list[GroupingFile[str]], known_authors: tuple[str, ...] | list[str] = ()
) -> Grouping[str]:
    return group_by_paths(files, parser(), known_authors=known_authors)


def run_content(
    scenario: Scenario,
    params: GroupingParams = CONTENT_PARAMS,
    known_authors: tuple[str, ...] | list[str] = (),
) -> Grouping[str]:
    return group_with_content(
        scenario.grouping_files(), scenario.content(), params, parser(), known_authors
    )


def partition(grouping: Grouping[str]) -> set[frozenset[str]]:
    """The grouping as a set of key sets (order-free)."""
    return {frozenset(g.keys) for g in grouping.groups}


def group_of(grouping: Grouping[str], key: str):
    """The group holding ``key``."""
    return next(g for g in grouping.groups if key in g.keys)


def by_prefix(keys: list[str] | set[str] | frozenset[str], prefix: str) -> set[str]:
    return {k for k in keys if k.startswith(prefix)}
