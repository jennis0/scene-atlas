"""Thresholds of variant grouping (design/variant-grouping-algorithm.md §9).

Encoder-independent values are the ``GroupingParams`` defaults, tuned on a benchmark of real
libraries (scene-atlas-learning); the embedding thresholds depend on the encoder and ship per model
(``grouping_calibration``).
"""

from __future__ import annotations

from dataclasses import dataclass

# a6 / scenes: a named folder is one map (one scene) when this share of its files has no identity
# at all (``Golden Forest/Night.webp``). The parser's ``group_files`` Pass 0 uses 0.7 for its rule.
VARIANT_ONLY_SHARE = 0.8


@dataclass(frozen=True)
class EmbeddingThresholds:
    """Embedding cosine thresholds; they depend on the encoder. The defaults are the medium
    encoder's (siglip2 base-384)."""

    agree: float = 0.70  # a3 / b3: embedding cosine of an agreeing pair (with the edge map)
    parent: float = 0.82  # c1: unit cohesion that lets a meaningful parent join its units
    whole_folder: float = 0.80  # c0: mean cohesion over every unit pair of the folder
    shared_base: float = 0.68  # a4 / b4 gate: cohesion of a gated shared-base family
    suggest: float = 0.66  # cohesion of a parent near-miss worth suggesting
    # a7: two units of a leaf are different maps below ``leaf_different``; with one weak cue
    # (names differ, or two variant sets) they are the same only with one production and
    # ``leaf_same_production``, or with ``leaf_same``
    leaf_different: float = 0.55
    leaf_same_production: float = 0.80
    leaf_same: float = 0.84
    # scenes (r5): embedding cosine of an agreeing scene pair (with ``scene_agree_edge``)
    scene_agree: float = 0.85


@dataclass(frozen=True)
class GroupingParams:
    """Thresholds of the walk and the scene rules.

    ``embedding`` is None when no calibration matches the active encoder: every rule that needs
    an embedding is then off (renditions, names and folders still work).
    """

    rendition_bits: int = 12  # pHash Hamming bits of 256
    rendition_aspect: float = 0.02  # |log aspect| difference of renditions
    agree_edge: float = 0.70  # edge-map correlation of an agreeing pair
    scene_agree_edge: float = 0.50  # ... of an agreeing scene pair (scenes share less layout)
    agree_aspect: float = 0.05
    agree_fraction: float = 0.25  # share of cross pairs that must agree to join two units
    big_family: int = 8  # a shared base over more units than this looks like a collection
    layout_overlap: float = 0.25  # mean cross edge correlation that raises unit cohesion
    aspect_tolerance: float = 0.03  # fingerprint: |log aspect| difference of compatible units
    canvas_tolerance: float = 0.02  # fingerprint: relative pixel-size difference of one canvas
    whole_folder_compatible: float = 0.9  # c0: share of unit pairs with compatible fingerprints
    whole_folder_max_units: int = 200  # c0 is not tried on folders with more units
    # Safety cap: a folder with more units is a container, and the leaf default is not tried.
    # Set well above the units of any single map.
    max_units: int = 40
    small_folder: int = 80  # all pairs are compared inside folders this small
    small_subtree: int = 150  # ... and inside subtrees this small
    big_join: int = 20  # x1 between two groups both this large is a suggestion; r6 never joins
    candidate_phash_bits: int = 20  # pHash candidate pairs (renditions need rendition_bits)
    knn_embedding: int = 25  # candidate neighbours per file by embedding
    knn_edge: int = 15  # candidate neighbours per file by edge map
    embedding: EmbeddingThresholds | None = None
