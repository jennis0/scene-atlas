"""Evaluate grid detection: 3-class classifier (square vs hex vs none).

Uses the 1D autocorrelation + rotation approach:
- Standard orientation (0deg/90deg) detects both square and hex periodicity
- 30deg rotation aligns hex grid lines (at 60deg/120deg) with the axes
- Period ratio distinguishes types: ~1.0 = square, ~0.866 = hex

Sweeps thresholds over the labelled dataset to find optimal decision
boundaries, then reports full diagnostics.

Usage:
    uv run python -m backend.eval_grid_detection           # full dataset
    uv run python -m backend.eval_grid_detection --quick   # ~50 per class
"""

import argparse
import math
import random
import sys
import time
from pathlib import Path

import cv2
import numpy as np
from scipy.signal import fftconvolve, find_peaks
from tqdm import tqdm

# Project imports
PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from backend.app.config import settings
from backend.app.models import Image, get_engine, get_session_local
from backend.app.services.image_parser import ImageParser
from backend.app.services.image_store import ImageStore

# ---------------------------------------------------------------------------
# Detection parameters
# ---------------------------------------------------------------------------
MIN_CELL_PX = 32
MAX_CELL_PX = 320
MAX_DIM = 20_000  # No resizing - full resolution
SQRT3_OVER_2 = math.sqrt(3) / 2  # ~ 0.866


# ---------------------------------------------------------------------------
# Core detection functions
# ---------------------------------------------------------------------------


def load_gray(path: Path, max_dim: int = MAX_DIM) -> tuple[np.ndarray, float]:
    img = cv2.imread(str(path), cv2.IMREAD_GRAYSCALE)
    if img is None:
        raise ValueError(f"Could not read image: {path}")
    h, w = img.shape
    scale = 1.0
    if max(h, w) > max_dim:
        scale = max_dim / max(h, w)
        img = cv2.resize(
            img, (max(1, int(w * scale)), max(1, int(h * scale))), interpolation=cv2.INTER_AREA
        )
    return img, scale


def canny_edges(img: np.ndarray) -> np.ndarray:
    med = np.median(img)
    return cv2.Canny(img, int(max(0, 0.5 * med)), int(min(255, 1.5 * med)))


def find_ac_peaks(
    projection: np.ndarray,
    min_p: int,
    max_p: int,
    min_prominence: float = 0.05,
    max_candidates: int = 5,
) -> list[tuple[int, float]]:
    n = len(projection)
    if n < min_p * 2:
        return []
    proj = projection.astype(np.float64)
    proj = proj - np.mean(proj)
    std = np.std(proj)
    if std < 1e-10:
        return []
    proj = proj / std
    ac = fftconvolve(proj, proj[::-1], mode="full")
    ac = ac[n - 1 :]
    z = ac[0]
    if z < 1e-10:
        return []
    ac = ac / z
    start, end = min_p, min(max_p + 1, len(ac))
    if start >= end:
        return []
    region = ac[start:end]
    peaks, props = find_peaks(region, prominence=min_prominence, distance=max(1, min_p // 2))
    if len(peaks) == 0:
        return []
    order = np.argsort(props["prominences"])[::-1][:max_candidates]
    candidates = []
    for idx in order:
        period = int(peaks[idx] + start)
        strength = float(ac[period])
        if strength > 0:
            candidates.append((period, min(1.0, strength)))
    candidates.sort(key=lambda x: x[0])
    return candidates


def pick_best_periods(
    h_candidates: list[tuple[int, float]],
    v_candidates: list[tuple[int, float]],
) -> tuple[int | None, float, int | None, float]:
    """Pick best (h_period, v_period) pair - square-only scoring."""
    if not h_candidates and not v_candidates:
        return None, 0.0, None, 0.0
    best_score = -1.0
    best_hp, best_hs, best_vp, best_vs = None, 0.0, None, 0.0
    if h_candidates and v_candidates:
        for hp, hs in h_candidates:
            for vp, vs in v_candidates:
                agreement = min(hp, vp) / max(hp, vp)
                strength = math.sqrt(hs * vs)
                size_bonus = 1.0 / (1.0 + max(hp, vp) * 0.001)
                score = agreement * strength * size_bonus
                if score > best_score:
                    best_score = score
                    best_hp, best_hs = hp, hs
                    best_vp, best_vs = vp, vs
    for hp, hs in h_candidates:
        if hs * 0.5 > best_score:
            best_score = hs * 0.5
            best_hp, best_hs = hp, hs
            best_vp, best_vs = None, 0.0
    for vp, vs in v_candidates:
        if vs * 0.5 > best_score:
            best_score = vs * 0.5
            best_hp, best_hs = None, 0.0
            best_vp, best_vs = vp, vs
    return best_hp, best_hs, best_vp, best_vs


def _run_1d_ac(edges: np.ndarray, min_c: int, max_c: int) -> dict:
    """Run 1D autocorrelation on an edge image, return features."""
    sh, sw = edges.shape
    if min_c >= max_c:
        return {
            "h_period": None,
            "v_period": None,
            "h_strength": 0.0,
            "v_strength": 0.0,
            "confidence": 0.0,
            "ratio": 0.0,
        }
    row_proj = np.mean(edges, axis=1, dtype=np.float64)
    col_proj = np.mean(edges, axis=0, dtype=np.float64)
    v_cands = find_ac_peaks(row_proj, min_c, max_c)
    h_cands = find_ac_peaks(col_proj, min_c, max_c)
    hp, hs, vp, vs = pick_best_periods(h_cands, v_cands)
    conf = math.sqrt(vs * hs) if vs > 0 and hs > 0 else max(vs, hs) * 0.5
    ratio = min(hp, vp) / max(hp, vp) if hp and vp else 0.0
    return {
        "h_period": hp,
        "v_period": vp,
        "h_strength": hs,
        "v_strength": vs,
        "confidence": conf,
        "ratio": ratio,
    }


def _rotate_edges(edges: np.ndarray, angle_deg: float) -> np.ndarray:
    """Rotate edge image, cropping borders to avoid artifacts."""
    sh, sw = edges.shape
    M = cv2.getRotationMatrix2D((sw / 2, sh / 2), angle_deg, 1.0)
    cos_a, sin_a = abs(M[0, 0]), abs(M[0, 1])
    new_w = int(sh * sin_a + sw * cos_a)
    new_h = int(sh * cos_a + sw * sin_a)
    M[0, 2] += (new_w - sw) / 2
    M[1, 2] += (new_h - sh) / 2
    rotated = cv2.warpAffine(edges, M, (new_w, new_h))
    margin = int(min(new_h, new_w) * 0.20)
    if margin > 0 and new_h > 2 * margin and new_w > 2 * margin:
        rotated = rotated[margin:-margin, margin:-margin]
    return rotated


def detect_grid(path: Path, orig_w: int, orig_h: int) -> dict:
    """Run detection at standard + rotated orientations.

    Returns a feature dict with:
    - Standard orientation: conf_std, ratio_std, hp_std, vp_std, ...
    - Rotated (30deg): conf_rot, ratio_rot, hp_rot, vp_rot, ...
    - Derived: hex_dev_std, hex_dev_rot, max_conf, best_ratio
    - Grid dimension predictions
    """
    img, scale = load_gray(path, MAX_DIM)
    edges = canny_edges(img)
    sh, sw = edges.shape
    min_c = max(4, int(MIN_CELL_PX * scale))
    max_c = min(min(sh, sw) // 3, int(MAX_CELL_PX * scale))

    # Standard orientation
    std = _run_1d_ac(edges, min_c, max_c)

    # 30deg rotation
    rot_edges = _rotate_edges(edges, 30)
    rh, rw = rot_edges.shape
    min_c_r = max(4, int(MIN_CELL_PX * scale))
    max_c_r = min(min(rh, rw) // 3, int(MAX_CELL_PX * scale))
    rot = _run_1d_ac(rot_edges, min_c_r, max_c_r)

    # Derived features
    max_conf = max(std["confidence"], rot["confidence"])
    hex_dev_std = abs(std["ratio"] - SQRT3_OVER_2) if std["ratio"] > 0 else 1.0
    hex_dev_rot = abs(rot["ratio"] - SQRT3_OVER_2) if rot["ratio"] > 0 else 1.0

    # Grid dimension predictions (using standard orientation periods)
    hp_orig = round(std["h_period"] / scale) if std["h_period"] else None
    vp_orig = round(std["v_period"] / scale) if std["v_period"] else None
    pred_grid_w = round(orig_w / vp_orig) if vp_orig else None
    pred_grid_h = round(orig_h / vp_orig) if vp_orig else None
    if pred_grid_w is None and hp_orig:
        pred_grid_w = round(orig_w / hp_orig)

    return {
        # Standard
        "conf_std": std["confidence"],
        "ratio_std": std["ratio"],
        "hp_std": std["h_period"],
        "vp_std": std["v_period"],
        "hs_std": std["h_strength"],
        "vs_std": std["v_strength"],
        # Rotated
        "conf_rot": rot["confidence"],
        "ratio_rot": rot["ratio"],
        "hp_rot": rot["h_period"],
        "vp_rot": rot["v_period"],
        "hs_rot": rot["h_strength"],
        "vs_rot": rot["v_strength"],
        # Derived
        "max_conf": max_conf,
        "hex_dev_std": hex_dev_std,
        "hex_dev_rot": hex_dev_rot,
        "scale": scale,
        # Dimensions
        "hp_orig": hp_orig,
        "vp_orig": vp_orig,
        "pred_grid_w": pred_grid_w,
        "pred_grid_h": pred_grid_h,
    }


# ---------------------------------------------------------------------------
# 3-class classification
# ---------------------------------------------------------------------------


def classify(
    r: dict,
    presence_conf: float,
    sq_ratio_min: float,
    hex_rot_conf: float,
) -> str:
    """Classify a detection result as 'square', 'hex', or 'none'.

    Decision tree:
    1. If max_conf < presence_conf -> none (not gridded)
    2. If conf_rot >= hex_rot_conf -> hex (rotation signal = hex)
    3. If conf_std >= presence_conf AND ratio_std >= sq_ratio_min -> square
    4. Else -> none

    Key insight: the 30deg rotation produces strong AC signal for hex grids
    (one set of hex lines aligns with vertical axis) but near-zero signal
    for square grids (both line sets are off-axis). This is the primary
    hex discriminator.
    """
    if r["max_conf"] < presence_conf:
        return "none"

    # Check hex: rotation signal is the key discriminator
    if r["conf_rot"] >= hex_rot_conf:
        return "hex"

    # Check square: standard orientation has strong signal with ratio ~1.0
    if r["conf_std"] >= presence_conf and r["ratio_std"] >= sq_ratio_min:
        return "square"

    return "none"


def confusion_matrix(preds: list[str], truths: list[str]) -> dict:
    """Compute 3-class confusion matrix and per-class metrics."""
    classes = ["square", "hex", "none"]
    matrix = {true: dict.fromkeys(classes, 0) for true in classes}
    for pred, truth in zip(preds, truths, strict=False):
        matrix[truth][pred] += 1

    # Per-class metrics
    metrics = {}
    total_correct = 0
    total = len(preds)
    for cls in classes:
        tp = matrix[cls][cls]
        total_correct += tp
        # How many of this true class did we get right?
        n_true = sum(matrix[cls].values())
        recall = tp / n_true if n_true > 0 else 0.0
        # How many predicted as this class are correct?
        n_pred = sum(matrix[t][cls] for t in classes)
        precision = tp / n_pred if n_pred > 0 else 0.0
        metrics[cls] = {
            "tp": tp,
            "n_true": n_true,
            "n_pred": n_pred,
            "recall": recall,
            "precision": precision,
        }

    overall_acc = total_correct / total if total > 0 else 0.0
    return {
        "matrix": matrix,
        "metrics": metrics,
        "overall_acc": overall_acc,
        "total_correct": total_correct,
        "total": total,
    }


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


def main():
    ap = argparse.ArgumentParser(description="Evaluate grid detection")
    ap.add_argument(
        "--quick", action="store_true", help="Sample ~50 per class for faster iteration"
    )
    ap.add_argument(
        "--per-class", type=int, default=50, help="Max samples per class in quick mode (default 50)"
    )
    args = ap.parse_args()

    mode = "QUICK" if args.quick else "FULL"
    print("=" * 90)
    print(f"GRID TYPE DETECTION EVALUATION (square vs hex vs none) [{mode}]")
    print(f"  MIN_CELL_PX={MIN_CELL_PX}  MAX_CELL_PX={MAX_CELL_PX}  MAX_DIM={MAX_DIM}")
    print("  Approach: 1D autocorrelation + 30deg rotation")
    print("=" * 90)

    # ------------------------------------------------------------------
    # Load images from DB (including hex)
    # ------------------------------------------------------------------
    parser = ImageParser(tag_categories=None)
    store = ImageStore(settings.store_images_dir)
    engine = get_engine(settings.database_url)
    SessionLocal = get_session_local(engine)
    db = SessionLocal()
    all_images = db.query(Image).all()

    samples = []
    no_label = 0

    for img in all_images:
        if img.media_type == "video" or img.image_type == "scene":
            continue
        p = parser.parse(img.filename, image_type=img.image_type or "battlemap")
        path = store._key_to_path(img.storage_key)
        if not path.exists():
            continue

        if p["gridded"] is None:
            no_label += 1
            continue

        # 3-class ground truth
        if p.get("grid_type") == "hex":
            truth_class = "hex"
        elif p["gridded"]:
            truth_class = "square"
        else:
            truth_class = "none"

        samples.append(
            {
                "filename": img.filename,
                "path": path,
                "width": img.width or 0,
                "height": img.height or 0,
                "truth_class": truth_class,
                "truth_grid_width": p.get("grid_width"),
                "truth_grid_height": p.get("grid_height"),
            }
        )

    db.close()

    n_sq = sum(1 for s in samples if s["truth_class"] == "square")
    n_hex = sum(1 for s in samples if s["truth_class"] == "hex")
    n_none = sum(1 for s in samples if s["truth_class"] == "none")
    print(
        f"\nFull dataset: {len(samples)} labelled images "
        f"({n_sq} square + {n_hex} hex + {n_none} none)"
    )
    print(f"  Skipped: {no_label} unlabelled")

    # Quick mode: stratified sample ~N per class
    if args.quick:
        n = args.per_class
        rng = random.Random(42)
        by_class = {"square": [], "hex": [], "none": []}
        for s in samples:
            by_class[s["truth_class"]].append(s)
        sampled = []
        for _cls, items in by_class.items():
            if len(items) <= n:
                sampled.extend(items)
            else:
                sampled.extend(rng.sample(items, n))
        rng.shuffle(sampled)
        samples = sampled
        n_sq = sum(1 for s in samples if s["truth_class"] == "square")
        n_hex = sum(1 for s in samples if s["truth_class"] == "hex")
        n_none = sum(1 for s in samples if s["truth_class"] == "none")
        print(
            f"  Quick mode: sampled {len(samples)} images "
            f"({n_sq} square + {n_hex} hex + {n_none} none)"
        )

    print()

    # ------------------------------------------------------------------
    # Run detection (standard + rotated)
    # ------------------------------------------------------------------
    print("Running detection (standard + 30deg rotation)...")
    results = []
    elapsed = 0.0
    errors = 0
    for s in tqdm(samples, desc="Detecting grids"):
        t0 = time.perf_counter()
        try:
            r = detect_grid(s["path"], s["width"], s["height"])
        except Exception as e:
            print(f"  ERROR on {s['filename']}: {e}")
            r = {
                "conf_std": 0.0,
                "ratio_std": 0.0,
                "hp_std": None,
                "vp_std": None,
                "hs_std": 0.0,
                "vs_std": 0.0,
                "conf_rot": 0.0,
                "ratio_rot": 0.0,
                "hp_rot": None,
                "vp_rot": None,
                "hs_rot": 0.0,
                "vs_rot": 0.0,
                "max_conf": 0.0,
                "hex_dev_std": 1.0,
                "hex_dev_rot": 1.0,
                "scale": 0.0,
                "hp_orig": None,
                "vp_orig": None,
                "pred_grid_w": None,
                "pred_grid_h": None,
            }
            errors += 1
        elapsed += time.perf_counter() - t0
        results.append(r)

    truths = [s["truth_class"] for s in samples]
    avg_ms = 1000 * elapsed / len(samples)
    print(
        f"\nProcessed {len(samples)} images in {elapsed:.1f}s "
        f"({avg_ms:.0f}ms/image, {errors} errors)\n"
    )

    # ------------------------------------------------------------------
    # Feature distribution by class
    # ------------------------------------------------------------------
    print("=" * 90)
    print("FEATURE DISTRIBUTIONS BY CLASS")
    print("=" * 90)

    for cls in ["square", "hex", "none"]:
        idx = [i for i, t in enumerate(truths) if t == cls]
        if not idx:
            continue
        confs_std = [results[i]["conf_std"] for i in idx]
        confs_rot = [results[i]["conf_rot"] for i in idx]
        ratios_std = [results[i]["ratio_std"] for i in idx]
        ratios_rot = [results[i]["ratio_rot"] for i in idx]
        hex_devs = [results[i]["hex_dev_std"] for i in idx]
        max_confs = [results[i]["max_conf"] for i in idx]

        print(f"\n  {cls.upper()} (n={len(idx)}):")
        print(
            f"    conf_std:   median={np.median(confs_std):.3f}  "
            f"mean={np.mean(confs_std):.3f}  "
            f"[{np.min(confs_std):.3f}, {np.max(confs_std):.3f}]"
        )
        print(
            f"    conf_rot:   median={np.median(confs_rot):.3f}  "
            f"mean={np.mean(confs_rot):.3f}  "
            f"[{np.min(confs_rot):.3f}, {np.max(confs_rot):.3f}]"
        )
        print(
            f"    max_conf:   median={np.median(max_confs):.3f}  "
            f"mean={np.mean(max_confs):.3f}  "
            f"[{np.min(max_confs):.3f}, {np.max(max_confs):.3f}]"
        )
        print(
            f"    ratio_std:  median={np.median(ratios_std):.3f}  "
            f"mean={np.mean(ratios_std):.3f}  "
            f"[{np.min(ratios_std):.3f}, {np.max(ratios_std):.3f}]"
        )
        print(
            f"    ratio_rot:  median={np.median(ratios_rot):.3f}  "
            f"mean={np.mean(ratios_rot):.3f}  "
            f"[{np.min(ratios_rot):.3f}, {np.max(ratios_rot):.3f}]"
        )
        print(
            f"    hex_dev:    median={np.median(hex_devs):.3f}  "
            f"mean={np.mean(hex_devs):.3f}  "
            f"[{np.min(hex_devs):.3f}, {np.max(hex_devs):.3f}]"
        )

    # ------------------------------------------------------------------
    # Threshold sweep (3-class)
    # ------------------------------------------------------------------
    print(f"\n{'=' * 90}")
    print("3-CLASS THRESHOLD SWEEP")
    print("=" * 90)
    print("  Decision tree:")
    print("    1. max_conf < presence_conf -> none")
    print("    2. conf_rot >= hex_rot_conf -> hex (rotation signal)")
    print("    3. conf_std >= presence_conf AND ratio_std >= sq_ratio -> square")
    print("    4. else -> none")

    presence_confs = np.arange(0.10, 0.70, 0.05)
    sq_ratio_mins = np.arange(0.88, 1.00, 0.02)
    hex_rot_confs = np.arange(0.05, 0.60, 0.025)

    best_acc = -1.0
    best_params = {}
    best_cm = None

    total_combos = len(presence_confs) * len(sq_ratio_mins) * len(hex_rot_confs)
    print(f"\n  Sweeping {total_combos:,} parameter combinations...")

    for pc in presence_confs:
        for sr in sq_ratio_mins:
            for hrc in hex_rot_confs:
                preds = [classify(r, pc, sr, hrc) for r in results]
                cm = confusion_matrix(preds, truths)
                acc = cm["overall_acc"]
                if acc > best_acc:
                    best_acc = acc
                    best_params = {
                        "presence_conf": pc,
                        "sq_ratio_min": sr,
                        "hex_rot_conf": hrc,
                    }
                    best_cm = cm

    # ------------------------------------------------------------------
    # Best result
    # ------------------------------------------------------------------
    print(f"\n{'=' * 90}")
    print("OPTIMAL PARAMETERS")
    print(f"{'=' * 90}")
    for k, v in best_params.items():
        print(f"  {k:<20} = {v:.2f}")
    print(f"\n  Overall accuracy: {100 * best_acc:.1f}%")

    # Confusion matrix
    print("\n  Confusion matrix (rows=truth, cols=predicted):")
    classes = ["square", "hex", "none"]
    cm = best_cm
    print(f"  {'':>12}", end="")
    for c in classes:
        print(f" {c:>8}", end="")
    print(f" {'recall':>8}")
    print(f"  {'-' * 48}")
    for true_cls in classes:
        print(f"  {true_cls:>12}", end="")
        for pred_cls in classes:
            val = cm["matrix"][true_cls][pred_cls]
            print(f" {val:>8}", end="")
        m = cm["metrics"][true_cls]
        print(f" {100 * m['recall']:>7.1f}%")

    print(f"  {'':>12}", end="")
    for pred_cls in classes:
        m = cm["metrics"][pred_cls]
        print(f" {100 * m['precision']:>7.1f}%", end="")
    print("  <- precision")

    # Per-class summary
    print("\n  Per-class metrics:")
    for cls in classes:
        m = cm["metrics"][cls]
        print(
            f"    {cls:>8}: recall={100 * m['recall']:.1f}%  "
            f"precision={100 * m['precision']:.1f}%  "
            f"(TP={m['tp']}/{m['n_true']})"
        )

    # ------------------------------------------------------------------
    # Apply optimal params and generate predictions
    # ------------------------------------------------------------------
    preds = [classify(r, **best_params) for r in results]

    # ------------------------------------------------------------------
    # Presence-only accuracy (gridded vs not, ignoring type)
    # ------------------------------------------------------------------
    print(f"\n{'=' * 90}")
    print("PRESENCE-ONLY ACCURACY (gridded vs none, ignoring type)")
    print(f"{'=' * 90}")
    tp = sum(1 for p, t in zip(preds, truths, strict=False) if p != "none" and t != "none")
    fn = sum(1 for p, t in zip(preds, truths, strict=False) if p == "none" and t != "none")
    tn = sum(1 for p, t in zip(preds, truths, strict=False) if p == "none" and t == "none")
    fp = sum(1 for p, t in zip(preds, truths, strict=False) if p != "none" and t == "none")
    n_pos = tp + fn
    n_neg = tn + fp
    total = n_pos + n_neg
    print(f"  TP={tp}  FN={fn}  TN={tn}  FP={fp}")
    print(f"  Recall:    {100 * tp / n_pos:.1f}%  (detect gridded)")
    print(f"  Precision: {100 * tp / (tp + fp):.1f}%  (gridded predictions correct)")
    print(f"  Accuracy:  {100 * (tp + tn) / total:.1f}%")

    # ------------------------------------------------------------------
    # Misclassification detail
    # ------------------------------------------------------------------
    print(f"\n{'=' * 90}")
    print("MISCLASSIFICATIONS")
    print(f"{'=' * 90}")

    for true_cls in classes:
        wrong = [
            (i, preds[i])
            for i in range(len(samples))
            if truths[i] == true_cls and preds[i] != true_cls
        ]
        if not wrong:
            continue
        print(f"\n  TRUE={true_cls} misclassified ({len(wrong)} images):")
        print(
            f"  {'#':>4}  {'Filename':<50} {'Pred':>6} "
            f"{'c_std':>5} {'r_std':>5} {'c_rot':>5} {'r_rot':>5} "
            f"{'hdev_s':>6} {'hdev_r':>6}"
        )
        print(f"  {'-' * 105}")
        for i, pred in wrong:
            s = samples[i]
            r = results[i]
            print(
                f"  {i:>4}  {s['filename']:<50} {pred:>6} "
                f"{r['conf_std']:>5.3f} {r['ratio_std']:>5.3f} "
                f"{r['conf_rot']:>5.3f} {r['ratio_rot']:>5.3f} "
                f"{r['hex_dev_std']:>6.3f} {r['hex_dev_rot']:>6.3f}"
            )

    # ------------------------------------------------------------------
    # Grid dimension estimation (on correctly classified square images)
    # ------------------------------------------------------------------
    print(f"\n{'=' * 90}")
    print("GRID DIMENSION ESTIMATION (correctly classified square images)")
    print(f"{'=' * 90}")

    w_errors, h_errors = [], []
    exact_w = exact_h = within_1_w = within_1_h = dim_samples = 0

    for i, r in enumerate(results):
        s = samples[i]
        if not (truths[i] == "square" and preds[i] == "square"):
            continue
        tw, th = s["truth_grid_width"], s["truth_grid_height"]
        if tw is None or th is None:
            continue
        dim_samples += 1
        pw, ph = r.get("pred_grid_w"), r.get("pred_grid_h")
        if pw is not None:
            err_w = pw - tw
            w_errors.append(err_w)
            if err_w == 0:
                exact_w += 1
            if abs(err_w) <= 1:
                within_1_w += 1
        if ph is not None:
            err_h = ph - th
            h_errors.append(err_h)
            if err_h == 0:
                exact_h += 1
            if abs(err_h) <= 1:
                within_1_h += 1

    if dim_samples > 0:
        print(f"\n  Evaluated on {dim_samples} correctly classified square images")
        if w_errors:
            w_arr = np.array(w_errors)
            print(
                f"\n  Width:  exact={exact_w}/{len(w_errors)} "
                f"({100 * exact_w / len(w_errors):.0f}%)  "
                f"within+/-1={within_1_w}/{len(w_errors)} "
                f"({100 * within_1_w / len(w_errors):.0f}%)  "
                f"mean_err={np.mean(np.abs(w_arr)):.2f}"
            )
        if h_errors:
            h_arr = np.array(h_errors)
            print(
                f"  Height: exact={exact_h}/{len(h_errors)} "
                f"({100 * exact_h / len(h_errors):.0f}%)  "
                f"within+/-1={within_1_h}/{len(h_errors)} "
                f"({100 * within_1_h / len(h_errors):.0f}%)  "
                f"mean_err={np.mean(np.abs(h_arr)):.2f}"
            )
    else:
        print("\n  No correctly classified square images with known dimensions.")

    # ------------------------------------------------------------------
    # Summary
    # ------------------------------------------------------------------
    print(f"\n{'=' * 90}")
    print("SUMMARY")
    print(f"{'=' * 90}")
    print(f"  3-class accuracy:   {100 * best_acc:.1f}%")
    for cls in classes:
        m = best_cm["metrics"][cls]
        print(
            f"    {cls:>8}: recall {100 * m['recall']:.1f}%, precision {100 * m['precision']:.1f}%"
        )
    print(f"  Presence accuracy:  {100 * (tp + tn) / total:.1f}%")
    print(f"  Speed:              {avg_ms:.0f}ms/image")
    print("\n  Optimal parameters (for production GridDetector):")
    for k, v in best_params.items():
        print(f"    {k} = {v:.2f}")


if __name__ == "__main__":
    main()
