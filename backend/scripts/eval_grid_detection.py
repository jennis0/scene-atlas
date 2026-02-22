"""Grid detection accuracy evaluation script.

Compares filename-based grid ground truth against the image-based GridDetector.

For every image in the database whose filename gives a definitive grid status
(gridded=True or False), the script:

  1. Uses ImageParser to extract ground truth (gridded, grid_type, grid_width, grid_height)
  2. Runs GridDetector on the actual image file
  3. Collects results into a CSV and prints accuracy metrics

Usage:
    uv run python -m backend.scripts.eval_grid_detection [--output results.csv]

Only images (media_type='image') are evaluated; videos are skipped.
Only battlemaps are evaluated by default; pass --include-scenes to also run
scenes through the detector (they're normally skipped in production).
"""

import argparse
import csv
import sys
from pathlib import Path

import numpy as np
from tqdm import tqdm

# ── Ensure project root is on sys.path ────────────────────────────────────────
PROJECT_ROOT = Path(__file__).parent.parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from backend.app.config import settings
from backend.app.models import Image, get_engine, get_session_local
from backend.app.services.grid_detector import GridDetector
from backend.app.services.image_parser import ImageParser
from backend.app.services.image_store import ImageStore

# ── Column headers ─────────────────────────────────────────────────────────────
CSV_FIELDS = [
    "image_id",
    "filename",
    "group",
    "subgroup",
    "name",
    "image_type",
    # Ground truth from filename parser
    "truth_gridded",
    "truth_grid_type",
    "truth_grid_width",
    "truth_grid_height",
    # Image-based detector output
    "det_gridded",
    "det_grid_type",
    "det_grid_width",
    "det_grid_height",
    "det_confidence",
    # Correctness flags
    "presence_correct",
    "type_correct",
    "width_error",
    "height_error",
]


def _yn(value: bool | None) -> str:
    if value is True:
        return "yes"
    if value is False:
        return "no"
    return ""


def _int_or(value, default: str = "") -> str:
    return str(value) if value is not None else default


def run(output_path: Path | None, include_scenes: bool, presence_threshold: float  = settings.grid_presence_threshold) -> None:
    parser = ImageParser(tag_categories=None)
    store = ImageStore(settings.store_images_dir)
    detector = GridDetector(
        min_cell_px=settings.grid_min_cell_px,
        max_cell_px=settings.grid_max_cell_px,
        max_dim=settings.grid_detection_max_dim,
        presence_threshold=presence_threshold,
        size_threshold=settings.grid_size_threshold,
    )

    engine = get_engine(settings.database_url)
    SessionLocal = get_session_local(engine)
    db = SessionLocal()
    try:
        images = db.query(Image).all()


        rows: list[dict] = []
        skipped_no_truth = 0
        skipped_video = 0
        skipped_missing = 0
        errors = 0

        for img in tqdm(images[:250]):
            # Skip videos — GridDetector works on still images only
            if img.media_type == "video":
                skipped_video += 1
                continue

            # Optionally skip scenes
            if not include_scenes and img.image_type == "scene":
                continue

            # ── Ground truth from filename ──────────────────────────────────────
            parsed = parser.parse(img.filename, image_type=img.image_type or "battlemap")
            truth_gridded: bool | None = parsed["gridded"]
            truth_grid_type: str | None = parsed.get("grid_type")
            truth_grid_width: int | None = parsed.get("grid_width")
            truth_grid_height: int | None = parsed.get("grid_height")

            if truth_gridded is None:
                skipped_no_truth += 1
                continue

            # ── Resolve image file path ─────────────────────────────────────────
            image_path = store._key_to_path(img.storage_key)
            if not image_path.exists():
                print(f"  MISSING: {image_path.name} (id={img.id})", file=sys.stderr)
                skipped_missing += 1
                continue

            # ── Run image-based detection ───────────────────────────────────────
            # Mirror ingestion logic: size_only when filename already confirmed gridded+sized
            size_only = truth_gridded is True and truth_grid_width is not None
            try:
                if size_only:
                    det_result = detector.detect_size_only(image_path, img.width or 0, img.height or 0)
                else:
                    det_result = detector.detect(image_path, img.width or 0, img.height or 0)
            except Exception as exc:
                print(f"  ERROR detecting {img.filename} (id={img.id}): {exc}", file=sys.stderr)
                errors += 1
                continue

            det_gridded = det_result["gridded"]
            det_grid_type = det_result["grid_type"]
            det_grid_width = det_result["grid_width"]
            det_grid_height = det_result["grid_height"]
            det_confidence = det_result["confidence"]

            # ── Correctness flags ───────────────────────────────────────────────
            presence_correct = (det_gridded == truth_gridded) if det_gridded is not None else None

            type_correct: bool | None = None
            if truth_gridded and truth_grid_type and det_grid_type:
                type_correct = det_grid_type == truth_grid_type

            width_error: int | None = None
            height_error: int | None = None
            if truth_grid_width is not None and det_grid_width is not None:
                width_error = abs(det_grid_width - truth_grid_width)
                height_error = abs(det_grid_height - truth_grid_height)  # type: ignore[operator]

            group_name = img.group.base_name if img.group else ""

            rows.append(
                {
                    "image_id": img.id,
                    "filename": img.filename,
                    "group": group_name,
                    "subgroup": img.subgroup or "",
                    "name": img.name or "",
                    "image_type": img.image_type or "",
                    "truth_gridded": _yn(truth_gridded),
                    "truth_grid_type": truth_grid_type or "",
                    "truth_grid_width": _int_or(truth_grid_width),
                    "truth_grid_height": _int_or(truth_grid_height),
                    "det_gridded": _yn(det_gridded),
                    "det_grid_type": det_grid_type or "",
                    "det_grid_width": _int_or(det_grid_width),
                    "det_grid_height": _int_or(det_grid_height),
                    "det_confidence": f"{det_confidence:.3f}" if det_confidence else "",
                    "presence_correct": _yn(presence_correct),
                    "type_correct": _yn(type_correct),
                    "width_error": _int_or(width_error),
                    "height_error": _int_or(height_error),
                }
            )
        
    finally:
        db.close()

    # ── Write CSV ───────────────────────────────────────────────────────────────
    if output_path:
        with open(output_path, "w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=CSV_FIELDS)
            writer.writeheader()
            writer.writerows(rows)
        print(f"\nWrote {len(rows)} rows → {output_path}")
    else:
        # Print to stdout
        writer = csv.DictWriter(sys.stdout, fieldnames=CSV_FIELDS)
        writer.writeheader()
        writer.writerows(rows)

    # ── Accuracy report ─────────────────────────────────────────────────────────
    total = len(rows)
    if total == 0:
        print("\nNo images with filename-derived ground truth found.")
        return

    # Grid presence
    presence_rows = [r for r in rows if r["presence_correct"] != ""]
    presence_correct_n = sum(1 for r in presence_rows if r["presence_correct"] == "yes")
    presence_pct = 100 * presence_correct_n / len(presence_rows) if presence_rows else 0

    # Breakdown: true-positive (gridded→detected) and true-negative (gridless→not detected)
    gridded_rows = [r for r in presence_rows if r["truth_gridded"] == "yes"]
    gridless_rows = [r for r in presence_rows if r["truth_gridded"] == "no"]
    tp = sum(1 for r in gridded_rows if r["presence_correct"] == "yes")
    tn = sum(1 for r in gridless_rows if r["presence_correct"] == "yes")

    # Grid type
    type_rows = [r for r in rows if r["type_correct"] != ""]
    type_correct_n = sum(1 for r in type_rows if r["type_correct"] == "yes")
    type_pct = 100 * type_correct_n / len(type_rows) if type_rows else 0

    square_rows = [r for r in type_rows if r["truth_grid_type"] == "square"]
    hex_rows = [r for r in type_rows if r["truth_grid_type"] == "hex"]
    sq_correct = sum(1 for r in square_rows if r["type_correct"] == "yes")
    hx_correct = sum(1 for r in hex_rows if r["type_correct"] == "yes")

    # Grid size
    size_rows = [r for r in rows if r["width_error"] != ""]
    if size_rows:
        w_errors = [int(r["width_error"]) for r in size_rows]
        h_errors = [int(r["height_error"]) for r in size_rows]
        mean_w_err = sum(w_errors) / len(w_errors)
        mean_h_err = sum(h_errors) / len(h_errors)
        within2_w = sum(1 for e in w_errors if e <= 2)
        within2_h = sum(1 for e in h_errors if e <= 2)
    else:
        mean_w_err = mean_h_err = 0.0
        within2_w = within2_h = 0

    sep = "─" * 60
    print(f"\n{sep}")
    print("  GRID DETECTION ACCURACY REPORT")
    print(sep)
    print(f"  Total images evaluated : {total}")
    print(f"  Skipped (no truth)     : {skipped_no_truth}")
    print(f"  Skipped (video)        : {skipped_video}")
    print(f"  Skipped (file missing) : {skipped_missing}")
    print(f"  Errors                 : {errors}")
    print()
    print("  GRID PRESENCE")
    print(f"    Overall accuracy   : {presence_correct_n}/{len(presence_rows)}  ({presence_pct:.1f}%)")
    print(f"    True positives     : {tp}/{len(gridded_rows)}  (gridded correctly detected)")
    print(f"    True negatives     : {tn}/{len(gridless_rows)}  (gridless correctly rejected)")
    print()
    print("  GRID TYPE  (gridded images with known filename type)")
    if type_rows:
        print(f"    Overall accuracy   : {type_correct_n}/{len(type_rows)}  ({type_pct:.1f}%)")
        print(f"    Square grids       : {sq_correct}/{len(square_rows)}")
        print(f"    Hex grids          : {hx_correct}/{len(hex_rows)}")
    else:
        print("    No images with comparable type data")
    print()
    print("  GRID SIZE  (images where filename has dimensions AND detector found dimensions)")
    if size_rows:
        print(f"    Sample count       : {len(size_rows)}")
        print(f"    Mean |width error| : {mean_w_err:.2f} cells")
        print(f"    Mean |height error|: {mean_h_err:.2f} cells")
        print(f"    Width within ±2    : {within2_w}/{len(size_rows)}  ({100*within2_w/len(size_rows):.1f}%)")
        print(f"    Height within ±2   : {within2_h}/{len(size_rows)}  ({100*within2_h/len(size_rows):.1f}%)")
    else:
        print("    No images with comparable dimension data")
    print(sep)


def sweep_thresholds(include_scenes: bool) -> None:
    """Sweep presence thresholds across confirmed-truth images only.

    Runs GridDetector.detect() with threshold=0 (so raw confidence is always
    returned), then applies thresholds in post-processing to build a
    precision/recall table without re-running detection.
    """
    file_parser = ImageParser(tag_categories=None)
    store = ImageStore(settings.store_images_dir)
    # threshold=0 ensures _run() never short-circuits — we get raw confidence
    detector = GridDetector(
        min_cell_px=settings.grid_min_cell_px,
        max_cell_px=settings.grid_max_cell_px,
        max_dim=settings.grid_detection_max_dim,
        presence_threshold=0.0,
        size_threshold=0.0,
    )

    engine = get_engine(settings.database_url)
    SessionLocal = get_session_local(engine)
    db = SessionLocal()
    try:
        images = db.query(Image).all()
    finally:
        db.close()

    # Only process images with known ground truth from filename
    confirmed = []
    for img in images:
        if img.media_type == "video":
            continue
        if not include_scenes and img.image_type == "scene":
            continue
        parsed = file_parser.parse(img.filename, image_type=img.image_type or "battlemap")
        if parsed["gridded"] is None:
            continue
        image_path = store._key_to_path(img.storage_key)
        if image_path.exists():
            confirmed.append((img, parsed["gridded"], image_path))

    print(f"Running full detect() on {len(confirmed)} confirmed-truth images…")

    samples: list[tuple[bool, float]] = []  # (truth_gridded, raw_confidence)
    for img, truth_gridded, image_path in tqdm(confirmed[:200]):
        try:
            det = detector.detect(image_path, img.width or 0, img.height or 0)
            samples.append((truth_gridded, det["confidence"]))
        except Exception:
            pass

    gridded_confs = sorted(c for g, c in samples if g)
    gridless_confs = sorted(c for g, c in samples if not g)

    sep = "─" * 70
    print(f"\n{sep}")
    print("  CONFIDENCE DISTRIBUTION")
    print(sep)
    print(f"  Confirmed gridded  : {len(gridded_confs)}")
    print(f"  Confirmed gridless : {len(gridless_confs)}")

    def _pct(vals: list[float]) -> str:
        if not vals:
            return "n/a"
        ps = np.percentile(vals, [10, 25, 50, 75, 90])
        return f"p10={ps[0]:.3f}  p25={ps[1]:.3f}  p50={ps[2]:.3f}  p75={ps[3]:.3f}  p90={ps[4]:.3f}"

    print(f"  Gridded  : {_pct(gridded_confs)}")
    print(f"  Gridless : {_pct(gridless_confs)}")

    n_pos = len(gridded_confs)
    n_neg = len(gridless_confs)
    n_total = len(samples)

    thresholds = [round(t, 2) for t in np.arange(0.10, 0.91, 0.05)]

    print(f"\n{sep}")
    print(f"  {'Thresh':>6}  {'TP':>4}  {'FN':>4}  {'TN':>4}  {'FP':>4}  {'TP%':>6}  {'TN%':>6}  {'Acc%':>6}")
    print(sep)
    for thresh in thresholds:
        tp = sum(1 for g, c in samples if g and c >= thresh)
        fn = sum(1 for g, c in samples if g and c < thresh)
        tn = sum(1 for g, c in samples if not g and c < thresh)
        fp = sum(1 for g, c in samples if not g and c >= thresh)
        tp_pct = 100 * tp / n_pos if n_pos else 0
        tn_pct = 100 * tn / n_neg if n_neg else 0
        acc = 100 * (tp + tn) / n_total if n_total else 0
        marker = "  ← current" if abs(thresh - settings.grid_presence_threshold) < 0.03 else ""
        print(f"  {thresh:>6.2f}  {tp:>4}  {fn:>4}  {tn:>4}  {fp:>4}  {tp_pct:>5.1f}%  {tn_pct:>5.1f}%  {acc:>5.1f}%{marker}")
    print(sep)


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument(
        "--output", "-o",
        metavar="FILE",
        help="Write CSV output to this file (default: stdout)",
    )
    ap.add_argument(
        "--include-scenes",
        action="store_true",
        help="Also run detector on scene images (normally skipped in production)",
    )
    ap.add_argument(
        "--sweep",
        action="store_true",
        help="Run presence-threshold sweep instead of full evaluation",
    )
    ap.add_argument(
        "--threshold", default=0.3, type=float,
    )
    args = ap.parse_args()

    if args.sweep:
        sweep_thresholds(include_scenes=args.include_scenes)
        return

    output_path = Path(args.output) if args.output else None
    run(output_path, include_scenes=args.include_scenes, presence_threshold=args.threshold)


if __name__ == "__main__":
    main()
