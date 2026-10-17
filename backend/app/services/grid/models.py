"""Trained grid models: ONNX sessions loaded once, on first use.

The models are small (a gradient-boosted presence classifier and a hex logistic
regression) and run on the CPU, single-threaded, so they never compete with CLIP for a
GPU or with the ingest pool for cores. ``meta.json`` pins the feature order each model
expects; it is checked against the code at load time so a stale or mismatched model
fails loudly instead of silently misclassifying.

Rebuild with ``scripts/models/grid/train_grid_models.py``.
"""

from __future__ import annotations

import json
import threading
from dataclasses import dataclass
from pathlib import Path

import numpy as np

MODEL_DIR = Path(__file__).resolve().parents[2] / "data" / "grid_models"

# Every feature the measurement code can produce; meta.json must only ask for these.
KNOWN_FEATURES = frozenset(
    {
        "joint", "sx", "sy", "minax", "odd", "log_mindim", "log_cell",
        "z_joint", "z_x", "z_y", "z_minax", "z_self", "null_mean", "null_sd",
        "hex", "hex_edges", "hex_pointy", "hex_flat",
        "hex2d", "hex2d_both", "sq2d", "sq2d_both",
        "contrast_x", "contrast_y", "contrast_min",
        "block_contrast_med", "block_contrast_min",
        "coverage_1.15", "coverage_1.3", "coverage_1.6",
        "polarity", "sign_agree",
    }
)  # fmt: skip


class GridModelError(RuntimeError):
    """The bundled grid models are missing or don't match the code."""


@dataclass(frozen=True)
class GridModels:
    presence: object  # onnxruntime.InferenceSession
    hex: object
    presence_features: tuple[str, ...]
    hex_features: tuple[str, ...]
    threshold: float
    sibling_prior_beta: float

    def presence_probability(self, x: list[float]) -> float:
        return _probability(self.presence, x)

    def hex_probability(self, x: list[float]) -> float:
        return _probability(self.hex, x)


def _probability(session, x: list[float]) -> float:
    """P(class 1) from a scikit-learn classifier exported by skl2onnx."""
    outputs = session.run(["probabilities"], {"x": np.asarray([x], dtype=np.float32)})
    return float(outputs[0][0, 1])


_models: GridModels | None = None
_lock = threading.Lock()


def load_models(model_dir: Path = MODEL_DIR) -> GridModels:
    """Load and validate the models from ``model_dir`` (no caching)."""
    import onnxruntime as ort

    meta_path = model_dir / "meta.json"
    try:
        meta = json.loads(meta_path.read_text())
    except (OSError, ValueError) as exc:
        raise GridModelError(f"Cannot read grid model metadata {meta_path}: {exc}") from exc

    presence_features = tuple(str(f) for f in meta.get("presence_features") or ())
    hex_features = tuple(str(f) for f in meta.get("hex_features") or ())
    unknown = (set(presence_features) | set(hex_features)) - KNOWN_FEATURES
    if not presence_features or not hex_features or unknown:
        raise GridModelError(
            f"Grid model metadata doesn't match this code (unknown features: {sorted(unknown)})"
        )

    opts = ort.SessionOptions()
    opts.intra_op_num_threads = 1
    opts.inter_op_num_threads = 1

    def session(name: str):
        path = model_dir / f"{name}.onnx"
        if not path.exists():
            raise GridModelError(f"Grid model file missing: {path}")
        sess = ort.InferenceSession(str(path), opts, providers=["CPUExecutionProvider"])
        n_inputs = sess.get_inputs()[0].shape[-1]
        expected = len(presence_features) if name.startswith("presence") else len(hex_features)
        if n_inputs != expected:
            raise GridModelError(
                f"{path.name} expects {n_inputs} features but meta.json lists {expected}"
            )
        return sess

    return GridModels(
        presence=session(f"presence_{meta['chosen_presence']}"),
        hex=session("hex_lr"),
        presence_features=presence_features,
        hex_features=hex_features,
        threshold=float(meta.get("threshold", 0.5)),
        sibling_prior_beta=float(meta.get("sibling_prior_beta", 0.3)),
    )


def get_models() -> GridModels:
    """The process-wide models, loaded on first use (thread-safe)."""
    global _models
    if _models is None:
        with _lock:
            if _models is None:
                _models = load_models()
    return _models
