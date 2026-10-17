"""Rebuild the grid detection models in ``backend/app/data/grid_models``.

Two steps, so the slow image analysis runs once and training can be repeated:

1. ``extract``: measure labelled images with the production code
   (``backend.app.services.grid.features.measure``) and write a features file.
2. ``train``: fit the presence and hex models from a features file, export them to
   ONNX (opset 17, loadable by every onnxruntime the app supports), write
   ``meta.json``, and check ONNX against scikit-learn on every training row.

The shipped models came from 2,278 gridded/gridless "twin" images from 28 creators,
plus hex maps labelled by file name and 1,100 synthetic hex images, all measured at
full resolution. Twin labels come from subtracting each gridded/gridless pair, which
leaves only the drawn grid. The method and evaluation are in
``design/grid-detection-v3.md``; the research scripts that built the datasets are kept
untracked in ``scripts/grid_research/``. The images are commercial artwork, so neither
they nor features derived from them are committed.

Usage (skl2onnx is needed only here, so it isn't a project dependency):

    uv run --extra cpu python scripts/models/grid/train_grid_models.py extract \\
        --labels labels.csv --out features.jsonl
    uv run --extra cpu --with skl2onnx==1.20.0 python scripts/models/grid/train_grid_models.py \\
        train --features features.jsonl --out backend/app/data/grid_models

labels.csv columns: ``path,width,height,creator,source,label`` where ``source`` is
``twin`` (presence label, ``label`` = ``square``/``hex``/``none``), ``filename`` (hex
label from the file name: ``label`` = ``hex``/``square``) or ``synthetic`` (hex only:
``label`` = ``hex``/``none``).

Features file: one JSON object per line, ``{"source", "label", "creator", "m"}`` where
``m`` holds the measurements. Row order matters for exact reproduction.
"""

from __future__ import annotations

import argparse
import csv
import json
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT))

# The settings the evaluation selected (design/grid-detection-v3.md, round 5). Changing
# them is a new model: re-run the cross-artist evaluation before shipping.
PRESENCE_GBM = {
    "max_depth": 3,
    "max_iter": 150,
    "learning_rate": 0.08,
    "l2_regularization": 1.0,
    "class_weight": "balanced",
}
HEX_LR_C = 0.5
THRESHOLD = 0.5
SIBLING_PRIOR_BETA = 0.3
TARGET_OPSET = 17

# Measurement keys the features (and derived features) are computed from.
_KEEP = {"width", "height", "cell", "sx", "sy", "z_x", "z_y", "contrast_x", "contrast_y", "ok"}


def extract(labels_path: Path, out_path: Path) -> None:
    from backend.app.services.grid.analysis import AnalysisParams
    from backend.app.services.grid.features import measure
    from backend.app.services.grid.models import KNOWN_FEATURES

    keep = KNOWN_FEATURES | _KEEP
    params = AnalysisParams()  # full resolution, as the shipped models expect
    with open(labels_path, newline="") as f_in, open(out_path, "w") as f_out:
        rows = list(csv.DictReader(f_in))
        for i, row in enumerate(rows, 1):
            m = measure(Path(row["path"]), int(row["width"]), int(row["height"]), params)
            if m is None:
                print(f"skip (unreadable): {row['path']}", file=sys.stderr)
                continue
            record = {
                "source": row["source"],
                "label": row["label"],
                "creator": row["creator"],
                "m": {k: v for k, v in m.items() if k in keep},
            }
            f_out.write(json.dumps(record) + "\n")
            if i % 100 == 0:
                print(f"{i}/{len(rows)}", file=sys.stderr)


def _patch_skl2onnx() -> None:
    """skl2onnx 1.20 with numpy 2 passes HistGradientBoosting's missing-value flags as
    numpy bools, which ONNX rejects ("Expected an int, got a boolean"); cast to int."""
    import skl2onnx.common.tree_ensemble as tree_ensemble

    original = tree_ensemble.add_node

    def add_node(*args, **kwargs):
        if "nodes_missing_value_tracks_true" in kwargs:
            kwargs["nodes_missing_value_tracks_true"] = int(
                kwargs["nodes_missing_value_tracks_true"]
            )
        return original(*args, **kwargs)

    tree_ensemble.add_node = add_node


def _export(model, n_features: int, path: Path):
    import onnxruntime as ort
    from skl2onnx import convert_sklearn
    from skl2onnx.common.data_types import FloatTensorType

    onx = convert_sklearn(
        model,
        initial_types=[("x", FloatTensorType([None, n_features]))],
        options={id(model): {"zipmap": False}},
        target_opset=TARGET_OPSET,
    )
    onx.graph.name = path.stem  # skl2onnx picks a random name; keep rebuilds byte-identical
    path.write_bytes(onx.SerializeToString())
    return ort.InferenceSession(str(path), providers=["CPUExecutionProvider"])


def train(
    features_path: Path, out_dir: Path, presence_features: list[str], hex_features: list[str]
) -> None:
    import numpy as np
    from sklearn.ensemble import HistGradientBoostingClassifier
    from sklearn.linear_model import LogisticRegression
    from sklearn.pipeline import make_pipeline
    from sklearn.preprocessing import StandardScaler

    from backend.app.services.grid.features import feature_vector

    rows = [json.loads(line) for line in features_path.read_text().splitlines() if line.strip()]
    twins = [r for r in rows if r["source"] == "twin"]
    hex_rows = twins + [r for r in rows if r["source"] == "filename"]
    synthetic = [r for r in rows if r["source"] == "synthetic"]
    if not twins:
        raise SystemExit("No twin rows: the presence model needs twin-labelled images")

    x_presence = np.array([feature_vector(r["m"], presence_features) for r in twins])
    y_presence = np.array([r["label"] != "none" for r in twins], dtype=int)
    presence = HistGradientBoostingClassifier(**PRESENCE_GBM).fit(x_presence, y_presence)

    x_hex = np.array([feature_vector(r["m"], hex_features) for r in hex_rows + synthetic])
    y_hex = np.array([r["label"] == "hex" for r in hex_rows + synthetic], dtype=int)
    hex_model = make_pipeline(StandardScaler(), LogisticRegression(C=HEX_LR_C, max_iter=3000))
    hex_model.fit(x_hex, y_hex)

    _patch_skl2onnx()
    out_dir.mkdir(parents=True, exist_ok=True)
    verification = {}
    for name, model, x in (("presence_gbm", presence, x_presence), ("hex_lr", hex_model, x_hex)):
        session = _export(model, x.shape[1], out_dir / f"{name}.onnx")
        p_sklearn = model.predict_proba(x)[:, 1]
        p_onnx = session.run(["probabilities"], {"x": x.astype(np.float32)})[0][:, 1]
        verification[name] = {
            "rows": int(len(x)),
            "max_abs_diff_onnx_vs_sklearn": float(np.max(np.abs(p_sklearn - p_onnx))),
            "decision_mismatches": int(np.sum((p_sklearn >= THRESHOLD) != (p_onnx >= THRESHOLD))),
        }
        print(name, verification[name])
        if verification[name]["decision_mismatches"]:
            raise SystemExit(f"{name}: ONNX disagrees with scikit-learn; not shipping")

    import sklearn

    meta = {
        "chosen_presence": "gbm",
        "presence_features": presence_features,
        "hex_features": hex_features,
        "threshold": THRESHOLD,
        "sibling_prior_beta": SIBLING_PRIOR_BETA,
        "decision": "hex if hex_p >= threshold; else gridded if presence_p >= threshold",
        "presence_params": PRESENCE_GBM,
        "hex_params": {"C": HEX_LR_C, "scaler": "standard"},
        "trained_at": "full resolution (max_analysis_dim=None)",
        "training_rows": {
            "twin": len(twins),
            "filename_hex": len(hex_rows) - len(twins),
            "synthetic": len(synthetic),
        },
        "creators": sorted(Counter(r["creator"] for r in twins)),
        "versions": {"scikit-learn": sklearn.__version__, "onnx_opset": TARGET_OPSET},
        "verification": verification,
    }
    (out_dir / "meta.json").write_text(json.dumps(meta, indent=1) + "\n")
    print("wrote", out_dir)


def record(labels_path: Path, out_path: Path) -> None:
    """Record the current detector's results on local images, for the opt-in regression
    test (``backend/tests/unit/test_grid_regression_local.py``). Re-record after a
    deliberate model change, and review the differences first."""
    from backend.app.services.grid import detect_grid

    with open(labels_path, newline="") as f_in, open(out_path, "w") as f_out:
        for row in csv.DictReader(f_in):
            path, w, h = Path(row["path"]), int(row["width"]), int(row["height"])
            case = {
                "path": str(path),
                "width": w,
                "height": h,
                "label": row.get("label"),
                "result": detect_grid(path, w, h),
                "size_only_result": detect_grid(path, w, h, size_only=True),
            }
            f_out.write(json.dumps(case) + "\n")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    sub = parser.add_subparsers(dest="command", required=True)
    p_record = sub.add_parser("record", help="Record results for the local regression test")
    p_record.add_argument("--labels", type=Path, required=True)
    p_record.add_argument("--out", type=Path, required=True)
    p_extract = sub.add_parser("extract", help="Measure labelled images")
    p_extract.add_argument("--labels", type=Path, required=True)
    p_extract.add_argument("--out", type=Path, required=True)
    p_train = sub.add_parser("train", help="Fit and export the models")
    p_train.add_argument("--features", type=Path, required=True)
    p_train.add_argument("--out", type=Path, required=True)
    p_train.add_argument(
        "--feature-order",
        type=Path,
        default=ROOT / "backend" / "app" / "data" / "grid_models" / "meta.json",
        help="meta.json whose feature lists (and order) to train with",
    )
    args = parser.parse_args()
    if args.command == "extract":
        extract(args.labels, args.out)
    elif args.command == "record":
        record(args.labels, args.out)
    else:
        order = json.loads(args.feature_order.read_text())
        train(args.features, args.out, order["presence_features"], order["hex_features"])


if __name__ == "__main__":
    main()
