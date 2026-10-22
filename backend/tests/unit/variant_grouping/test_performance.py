"""Performance smoke tests: the seal pass must keep up with large imports (design §3)."""

import time

import pytest

from backend.app.services.variant_grouping import GroupingFile, group_by_paths, group_with_content

from .support import CONTENT_PARAMS, Look, features, parser

# Targets: ~2 s for 20k paths, ~20 s for 10k files with content (CPU). Budgets leave headroom
# for slow CI machines; a regression past them is a real slowdown, not noise.
PATHS_ONLY_BUDGET_S = 3.0
CONTENT_BUDGET_S = 30.0

_WORDS = [
    "forest",
    "road",
    "cave",
    "temple",
    "tavern",
    "tower",
    "castle",
    "swamp",
    "river",
    "camp",
    "crypt",
    "market",
    "harbor",
]


def library(n: int) -> list[tuple[str, Look]]:
    """A synthetic library: 50 makers, maps of 10 files (grid folders × variants)."""
    out: list[tuple[str, Look]] = []
    m = 0
    while len(out) < n:
        maker = f"Maker {m % 50}"
        name = f"{_WORDS[m % 13].title()} {_WORDS[(m // 13) % 13].title()} {m}"
        slug = name.replace(" ", "_")
        for r, grid in enumerate(("Gridded", "Gridless")):
            for v, variant in enumerate(("Day", "Night", "Snow", "Rain", "Fog")):
                path = f"{maker}/{name}/{grid}/{slug}_{variant}_30x30.jpg"
                out.append((path, Look(name, theme=maker, variant=v, rendition=r)))
        m += 1
    return out[:n]


def test_paths_only_on_20k_files():
    files = [GroupingFile(p, p) for p, _ in library(20_000)]
    start = time.perf_counter()
    g = group_by_paths(files, parser())
    elapsed = time.perf_counter() - start
    assert len(g.groups) == 2_000
    assert elapsed < PATHS_ONLY_BUDGET_S, f"{elapsed:.2f} s"


@pytest.mark.heavy
def test_content_on_10k_files():
    lib = library(10_000)
    files = [GroupingFile(p, p) for p, _ in lib]
    content = {p: features(look) for p, look in lib}
    start = time.perf_counter()
    g = group_with_content(files, content, CONTENT_PARAMS, parser())
    elapsed = time.perf_counter() - start
    assert len(g.groups) <= 1_000
    assert elapsed < CONTENT_BUDGET_S, f"{elapsed:.2f} s"
