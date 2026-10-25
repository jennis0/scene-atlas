"""Learned group names and authors: candidate token runs of the members' paths, and the rule
names, scored by bundled gradient-boosted trees (design/variant-grouping-algorithm.md §8).

The feature code must match the models and tables in ``backend/app/data/group_naming/``;
``creators.json`` there lists known creators (names and aliases) for authors.
"""

from __future__ import annotations

import json
import logging
from functools import cache
from pathlib import Path

import numpy as np

from .namer import WalkNamer
from .text import Tables, author_key

__all__ = ["ASSET_DIR", "LearnedNamer", "WalkNamer", "author_key", "load"]

logger = logging.getLogger(__name__)

ASSET_DIR = Path(__file__).resolve().parents[3] / "data" / "group_naming"


class LearnedNamer:
    """The bundled models and tables (stateless; one per process, see ``load``)."""

    def __init__(self, asset_dir: Path):
        import onnxruntime as ort

        opts = ort.SessionOptions()
        opts.intra_op_num_threads = 1
        opts.inter_op_num_threads = 1
        self._sessions = {
            k: ort.InferenceSession(
                str(asset_dir / f"{k}.onnx"), opts, providers=["CPUExecutionProvider"]
            )
            for k in ("point", "pair", "author", "identity")
        }
        self.tables = Tables(json.loads((asset_dir / "tables.json").read_text(encoding="utf-8")))
        creators = json.loads((asset_dir / "creators.json").read_text(encoding="utf-8"))["creators"]
        self.creators: dict[str, str] = {}  # packaged creators: author_key of name or alias -> name
        for c in creators:
            for alias in (c["name"], *c["aliases"]):
                self.creators.setdefault(author_key(alias), c["name"])

    def predict(self, model: str, x: np.ndarray) -> np.ndarray:
        """Severity (``point``, lower is better) or P(yes) of the other models, per row."""
        x = np.ascontiguousarray(x, dtype=np.float64)
        return np.asarray(self._sessions[model].run(None, {"x": x})[0])


@cache
def load() -> LearnedNamer | None:
    """The process-wide namer, or None (naming falls back to the rules) when the assets fail."""
    try:
        return LearnedNamer(ASSET_DIR)
    except Exception:
        logger.exception("Learned group naming unavailable; using the naming rules")
        return None
