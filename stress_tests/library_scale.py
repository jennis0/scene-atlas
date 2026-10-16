"""Read-path benchmark against a synthetic large library (no HTTP, no models).

Builds a SQLite library of N images directly (groups of ~7, 4 tags and 5
colours per image, migrated to the current schema), then reports the SQL
query count and wall time of the search, gallery, group and tag read paths.
Semantic search is replaced by a fake returning random candidates.

    uv run python -m stress_tests.library_scale build 56000 --db /tmp/lib.db
    uv run python -m stress_tests.library_scale run --db /tmp/lib.db

Use it to check a change for N+1 queries or slow aggregates at the scale of a
real library (the reference library is ~56k images). Never point it at a real
library database: ``build`` deletes the file first.
"""

from __future__ import annotations

import argparse
import random
import sqlite3
import time
import tracemalloc
from collections.abc import Callable
from datetime import datetime, timedelta
from pathlib import Path
from unittest.mock import MagicMock, patch

from pydantic import TypeAdapter
from sqlalchemy import event

from backend.app.api import groups as groups_api
from backend.app.api import images as images_api
from backend.app.api import tags as tags_api
from backend.app.models import get_engine, get_session_local, init_db
from backend.app.models.schemas import GroupDetailResponse, ImageResponse
from backend.app.services import search_service
from backend.app.services.color_search import ColorIndex
from backend.app.services.search_service import SearchFilters, SearchMode

_WORDS = (
    "forest cave dungeon tavern castle ruins swamp desert snow river bridge temple "
    "crypt market harbor ship tower village camp mine"
).split()
_AUTHORS = [f"Author{i}" for i in range(120)]
_TAGS = {
    "season": ["winter", "summer", "autumn", "spring"],
    "lighting": ["day", "night", "dusk", "torch"],
    "terrain": ["forest", "cave", "urban", "desert", "snow", "swamp"],
    "weather": ["rain", "fog", "clear", "storm"],
}


def build(path: Path, n: int) -> None:
    path.unlink(missing_ok=True)
    engine = get_engine(f"sqlite:///{path}")
    init_db(engine)
    engine.dispose()

    rng = random.Random(1)
    base = datetime(2025, 1, 1)
    n_groups = max(1, n // 7)
    groups = [
        (
            g,
            f"{rng.choice(_WORDS).title()} {rng.choice(_WORDS).title()} {g}",
            rng.choice(_AUTHORS),
            (base + timedelta(minutes=g)).isoformat(" "),
        )
        for g in range(1, n_groups + 1)
    ]
    images, tags, colors = [], [], []
    for i in range(1, n + 1):
        group_id, group_name, author, _ = groups[(i - 1) % n_groups]
        name = f"{group_name} v{i}"
        gridded = rng.choice([True, False, None])
        image_tags = [(c, rng.choice(v)) for c, v in _TAGS.items()]
        images.append(
            (
                i,
                f"f{i}.jpg",
                f"k{i}.jpg",
                name,
                author,
                group_id,
                gridded,
                rng.choice(["square", "hex"]) if gridded else None,
                " ".join([name, author, *(v for _, v in image_tags)]),
                "video" if rng.random() < 0.05 else "image",
                rng.choice(["battlemap", "battlemap", "scene"]),
                (base + timedelta(seconds=i * 37)).isoformat(" "),
                base.isoformat(" "),
                f"t{i}_400x400.jpg",
            )
        )
        tags += [(i, c, v, 1.0, "auto", base.isoformat(" ")) for c, v in image_tags]
        colors += [(i, f"#{rng.randrange(1 << 24):06x}", 20.0, o) for o in range(1, 6)]

    con = sqlite3.connect(path)
    con.executemany(
        "INSERT INTO variant_groups (id, base_name, author, image_count, created_at) "
        "VALUES (?,?,?,0,?)",
        groups,
    )
    con.executemany(
        "INSERT INTO images (id, filename, storage_key, name, author, variant_group_id, "
        "gridded, grid_type, search_text, media_type, image_type, created_at, updated_at, "
        "thumbnail_key) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
        images,
    )
    con.executemany(
        "INSERT INTO tags (image_id, category, value, confidence, source, created_at) "
        "VALUES (?,?,?,?,?,?)",
        tags,
    )
    con.executemany(
        "INSERT INTO colors (image_id, color_hex, percentage, color_order) VALUES (?,?,?,?)",
        colors,
    )
    con.execute(
        "UPDATE variant_groups SET primary_image_id = "
        "(SELECT MIN(id) FROM images WHERE variant_group_id = variant_groups.id)"
    )
    con.commit()
    con.execute("ANALYZE")
    con.close()


def _cases(n: int) -> list[tuple[str, Callable]]:
    f, hybrid = SearchFilters, SearchMode.HYBRID
    images = TypeAdapter(list[ImageResponse])
    return [
        ("facets", lambda db: search_service.get_facets(db)),
        (
            "browse images, limit 500",
            lambda db: search_service.browse_images(db, f(), "created_at", "desc", 500, 0),
        ),
        (
            "browse images, colour filter",
            lambda db: search_service.browse_images(
                db, f(colors=("#808080",)), "created_at", "desc", 500, 0
            ),
        ),
        (
            "hybrid search, limit 500",
            lambda db: search_service.search_images(
                db, "forest night", hybrid, f(), "relevance", "desc", 500, 0
            ),
        ),
        (
            "hybrid search, limit 2000",
            lambda db: search_service.search_images(
                db, "forest night", hybrid, f(), "relevance", "desc", 2000, 0
            ),
        ),
        (
            "browse groups, limit 50",
            lambda db: search_service.browse_groups(db, f(), "created_at", "desc", 50, 0, True),
        ),
        (
            "browse groups, tag filter, limit 200",
            lambda db: search_service.browse_groups(
                db, f(tags=("season:winter",)), "created_at", "desc", 200, 0, False
            ),
        ),
        (
            "search groups, limit 50",
            lambda db: search_service.search_groups(db, "cave", hybrid, f(), 50, 0, True),
        ),
        (
            "search groups, limit 500",
            lambda db: search_service.search_groups(db, "cave", hybrid, f(), 500, 0, False),
        ),
        (
            "list images, limit 100",
            lambda db: images.validate_python(images_api.list_images(skip=0, limit=100, db=db)),
        ),
        (
            "group detail",
            lambda db: GroupDetailResponse.model_validate(groups_api.get_group(group_id=5, db=db)),
        ),
        ("tag values", lambda db: tags_api.get_tag_values_for_category("lighting", db=db)),
    ]


def run(path: Path) -> None:
    engine = get_engine(f"sqlite:///{path}")
    Session = get_session_local(engine)
    n = sqlite3.connect(path).execute("SELECT max(id) FROM images").fetchone()[0]
    rng = random.Random(2)
    fake_clip = MagicMock()
    fake_clip.encode_text.return_value = [0.0] * 512
    fake_vectors = MagicMock()
    fake_vectors.search_similar.side_effect = lambda *a, limit=100, **k: [
        {"image_id": rng.randrange(1, n + 1), "score": rng.random()} for _ in range(limit)
    ]
    statements: list[str] = []
    event.listen(engine, "before_cursor_execute", lambda *a: statements.append(a[2]))

    with (
        patch.object(search_service, "get_clip_service", lambda: fake_clip),
        patch.object(search_service, "get_lancedb_service", lambda: fake_vectors),
    ):
        print(f"{n} images")
        for name, case in _cases(n):
            with Session() as db:
                case(db)  # warm process-wide caches (colour index, aliases)
            with Session() as db:
                statements.clear()
                start = time.perf_counter()
                case(db)
                elapsed = time.perf_counter() - start
            print(f"{name:40s} {len(statements):5d} queries {elapsed * 1000:9.1f} ms")

    tracemalloc.start()
    index = ColorIndex()
    with Session() as db:
        index.find_images_by_colors(db, ["#808080"])
    current, peak = tracemalloc.get_traced_memory()
    tracemalloc.stop()
    print(f"{'colour index memory':40s} {current / 1e6:.1f} MB retained, {peak / 1e6:.1f} MB peak")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("command", choices=["build", "run"])
    parser.add_argument("images", type=int, nargs="?", default=56_000)
    parser.add_argument("--db", type=Path, required=True)
    args = parser.parse_args()
    if args.command == "build":
        build(args.db, args.images)
    else:
        run(args.db)


if __name__ == "__main__":
    main()
