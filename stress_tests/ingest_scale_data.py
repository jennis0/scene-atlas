"""Synthetic battlemap folders for ``ingest_scale``: real, distinct, decodable images under
creator / map / variant names the parser groups (design/parser.md).

Every file is drawn from its own seed: a map's layout (floor, rooms, trees, a path) comes
from the map's seed, so its variants look alike; each variant recolours it (night, snow,
fey…) and adds its own props and noise, so bytes, pixels and perceptual hashes all differ.
Some variants carry grid lines and a ``[gridded] 30x20`` name, some sit in ``Gridded`` /
``Gridless`` sub-folders, a few are PNGs, and a few are horizon "scenes".

Deterministic: the same ``(n, seed)`` gives the same paths and bytes on any machine.
"""

from __future__ import annotations

import hashlib
import io
import os
import random
from collections.abc import Iterator
from dataclasses import asdict, dataclass
from multiprocessing import Pool
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw

CREATORS = [
    "Lantern Cartography",
    "Hexfield Studio",
    "Mossy Flagon Maps",
    "Ninefold Atlas",
    "Brine and Bramble",
    "Copperquill",
    "Stoneguard Tiles",
    "Wyrmroost Press",
    "Gloamwood Maps",
    "Saltmarsh Cartel",
    "Ironvale Prints",
    "Duskfall Designs",
]
ADJECTIVES = [
    "Sunken", "Forgotten", "Burning", "Hidden", "Frozen", "Whispering", "Crimson",
    "Shattered", "Gilded", "Drowned", "Hollow", "Ancient", "Silent", "Verdant", "Ashen",
    "Moonlit", "Broken", "Howling", "Twisted", "Emerald",
]  # fmt: skip
NOUNS = [
    "Temple", "Crypt", "Tavern", "Harbour", "Watchtower", "Mine", "Bridge", "Grove",
    "Keep", "Market", "Shrine", "Camp", "Sewers", "Library", "Lighthouse", "Monastery",
    "Quarry", "Bazaar", "Outpost", "Caverns", "Wharf", "Chapel", "Mill", "Gatehouse",
]  # fmt: skip
VARIANTS = [
    "Day", "Night", "Snow", "Fey", "Infernal", "Rain", "Autumn", "Summer", "Fog",
    "Ruined", "Shadow", "Spring", "Sunset", "Flooded",
]  # fmt: skip
SIZES = [(512, 512), (768, 512), (512, 768), (640, 640), (1024, 1024), (1280, 896)]
SIZE_WEIGHTS = [3, 2, 2, 2, 2, 1]


@dataclass(frozen=True)
class Planned:
    rel: str  # POSIX path under the dataset root: Creator/Map/…/file
    seed: int  # the file's own seed
    map_seed: int  # its map's layout
    variant: str
    width: int
    height: int
    grid: int  # cell size in px drawn on it; 0 = none
    fmt: str  # "JPEG" or "PNG"
    scene: bool


def _map_files(rng: random.Random, creator: str, name: str, map_seed: int) -> list[dict]:
    """One map's variants, as kwargs for ``Planned`` (seed and rel filled in later)."""
    width, height = rng.choices(SIZES, SIZE_WEIGHTS)[0]
    variants = rng.sample(VARIANTS, rng.randint(2, 9))
    compact = name.replace(" ", "")
    layout = rng.choice(["flat", "flat", "flat", "grid_folders", "marked"])
    cols, rows = width // 32, height // 32
    files = []
    for v in variants:
        fmt = "PNG" if rng.random() < 0.03 else "JPEG"
        ext = "png" if fmt == "PNG" else "jpg"
        base = {"map_seed": map_seed, "variant": v, "width": width, "height": height, "fmt": fmt}
        if layout == "grid_folders":
            files.append(
                dict(
                    base,
                    rel=f"{creator}/{name}/Gridded/{compact}_{v}_{cols}x{rows}.{ext}",
                    grid=32,
                    scene=False,
                )
            )
            files.append(
                dict(
                    base, rel=f"{creator}/{name}/Gridless/{compact}_{v}.{ext}", grid=0, scene=False
                )
            )
        elif layout == "marked":
            gridded = rng.random() < 0.5
            label = f" [gridded] {cols}x{rows}" if gridded else ""
            files.append(
                dict(
                    base,
                    rel=f"{creator}/{name}/{name}_{v}{label}.{ext}",
                    grid=32 if gridded else 0,
                    scene=False,
                )
            )
        else:
            files.append(dict(base, rel=f"{creator}/{name}/{name}_{v}.{ext}", grid=0, scene=False))
    if rng.random() < 0.15:  # a vista of the place, which Auto should call a scene
        files.append(
            {
                "map_seed": map_seed,
                "variant": "Vista",
                "width": 1024,
                "height": 576,
                "fmt": "JPEG",
                "rel": f"{creator}/{name}/Scenes/{name} Vista.jpg",
                "grid": 0,
                "scene": True,
            }
        )
    return files


def plan(n: int, seed: int = 1, start: int = 0) -> list[Planned]:
    """``n`` files, grouped into maps of 2–18 variants under a dozen creators. ``start``
    offsets the seeds and names, for files added later that must not repeat these."""
    rng = random.Random(seed * 1_000_003 + start)
    out: list[Planned] = []
    used: set[tuple[str, str]] = set()
    m = 0
    while len(out) < n:
        creator = rng.choice(CREATORS)
        name = f"{rng.choice(ADJECTIVES)} {rng.choice(NOUNS)}"
        k = 2
        while (creator, name) in used:
            name = f"{name.rsplit(' ', 1)[0]} {k}" if k > 2 else f"{name} {k}"
            k += 1
        used.add((creator, name))
        if start:
            name = f"{name} Redux {start}"
        map_seed = seed * 10_000_000 + start + m
        for f in _map_files(rng, creator, name, map_seed):
            out.append(Planned(seed=seed * 100_000_000 + start + len(out), **f))
        m += 1
    return out[:n]


# ── Drawing ─────────────────────────────────────────────────────────────────

_TINTS = {
    "Day": (1.0, 1.0, 1.0, 0),
    "Night": (0.35, 0.4, 0.7, 0),
    "Snow": (1.1, 1.1, 1.2, 80),
    "Fey": (0.9, 0.6, 1.2, 20),
    "Infernal": (1.3, 0.5, 0.3, 0),
    "Rain": (0.7, 0.75, 0.85, 10),
    "Autumn": (1.2, 0.8, 0.4, 0),
    "Summer": (1.05, 1.1, 0.8, 10),
    "Fog": (0.8, 0.8, 0.8, 70),
    "Ruined": (0.75, 0.7, 0.65, 0),
    "Shadow": (0.3, 0.3, 0.4, 0),
    "Spring": (0.8, 1.2, 0.8, 10),
    "Sunset": (1.3, 0.8, 0.6, 0),
    "Flooded": (0.5, 0.8, 1.2, 0),
    "Vista": (1.0, 1.0, 1.0, 0),
}


def _layout(p: Planned) -> Image.Image:
    """The map's own layout: the same for every variant of one map."""
    r = random.Random(p.map_seed)
    floor = tuple(r.randint(60, 180) for _ in range(3))
    img = Image.new("RGB", (p.width, p.height), floor)
    d = ImageDraw.Draw(img)
    for _ in range(r.randint(2, 6)):  # rooms
        x0, y0 = r.randrange(0, p.width - 60), r.randrange(0, p.height - 60)
        x1, y1 = x0 + r.randint(60, p.width // 2), y0 + r.randint(60, p.height // 2)
        fill = tuple(r.randint(90, 220) for _ in range(3))
        d.rectangle((x0, y0, x1, y1), fill=fill, outline=(30, 25, 20), width=r.randint(4, 10))
    for _ in range(r.randint(5, 30)):  # trees and rocks
        x, y, s = r.randrange(p.width), r.randrange(p.height), r.randint(8, 40)
        d.ellipse((x - s, y - s, x + s, y + s), fill=(r.randint(20, 70), r.randint(80, 150), 40))
    pts = [(r.randrange(p.width), r.randrange(p.height)) for _ in range(4)]
    d.line(pts, fill=(150, 120, 80), width=r.randint(10, 30))  # a path
    return img


def _scene(p: Planned) -> Image.Image:
    """A horizon picture: sky gradient, hills, a building."""
    r = random.Random(p.map_seed)
    h = np.linspace(0, 1, p.height)[:, None, None]
    sky = (
        np.array([r.randint(80, 160), r.randint(120, 200), 255]) * (1 - h)
        + np.array([255, 220, 180]) * h
    )
    arr = np.broadcast_to(sky, (p.height, p.width, 3)).astype(np.uint8).copy()
    img = Image.fromarray(arr, "RGB")
    d = ImageDraw.Draw(img)
    horizon = int(p.height * r.uniform(0.5, 0.7))
    d.polygon(
        [(0, p.height), *[(x, horizon - r.randint(0, 80)) for x in range(0, p.width + 64, 64)],
         (p.width, p.height)],
        fill=(40, r.randint(80, 130), 50),
    )  # fmt: skip
    bx = r.randrange(p.width // 4, 3 * p.width // 4)
    d.rectangle((bx, horizon - 160, bx + 90, horizon), fill=(90, 80, 75))
    d.polygon([(bx - 10, horizon - 160), (bx + 45, horizon - 230), (bx + 100, horizon - 160)],
              fill=(120, 40, 30))  # fmt: skip
    return img


def render(p: Planned) -> bytes:
    img = _scene(p) if p.scene else _layout(p)
    r = random.Random(p.seed)
    d = ImageDraw.Draw(img)
    for _ in range(r.randint(3, 12)):  # this variant's own props
        x, y, s = r.randrange(p.width), r.randrange(p.height), r.randint(4, 16)
        d.rectangle((x, y, x + s, y + s), fill=tuple(r.randint(0, 255) for _ in range(3)))
    arr = np.asarray(img, dtype=np.float32)
    tr, tg, tb, fog = _TINTS[p.variant]
    arr = arr * np.array([tr, tg, tb], dtype=np.float32) + fog
    noise = np.random.default_rng(p.seed).normal(0, 6, arr.shape[:2])[..., None]
    arr = np.clip(arr + noise, 0, 255).astype(np.uint8)
    if p.grid:
        arr[:: p.grid, :, :] = 20
        arr[:, :: p.grid, :] = 20
    buf = io.BytesIO()
    out = Image.fromarray(arr, "RGB")
    if p.fmt == "PNG":
        out.save(buf, format="PNG", compress_level=1)
    else:
        out.save(buf, format="JPEG", quality=82 + p.seed % 10)
    return buf.getvalue()


def _write(args: tuple[Path, Planned]) -> dict:
    root, p = args
    data = render(p)
    path = root / p.rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)
    return {"rel": p.rel, "sha256": hashlib.sha256(data).hexdigest(), "size": len(data)}


def generate(root: Path, files: list[Planned], workers: int | None = None) -> list[dict]:
    """Write ``files`` under ``root``; returns ``{rel, sha256, size}`` per file, in order."""
    root.mkdir(parents=True, exist_ok=True)
    with Pool(workers or os.cpu_count() or 2) as pool:
        return pool.map(_write, [(root, p) for p in files], chunksize=32)


def describe(files: list[Planned]) -> Iterator[dict]:
    for p in files:
        yield asdict(p)
