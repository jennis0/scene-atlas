"""Image labeling pipeline: prepare thumbnails/batches, init runs, track status."""

from __future__ import annotations

import argparse
import json
import random
import sys
from datetime import UTC, datetime
from pathlib import Path

from PIL import Image

IMAGE_EXTENSIONS = {".jpg", ".jpeg", ".png", ".gif", ".webp"}
MAX_DIMENSION = 7999
THUMBNAIL_MAX_SIZE = 800
BATCH_SIZE = 10


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def relpath_to_thumbnail_name(relpath: str) -> str:
    """Convert a relative path to a flat thumbnail filename.

    Replaces directory separators with '__' to flatten subdirectories.
    e.g. 'subfolder/Map.jpg' -> 'subfolder__Map.jpg'
    """
    return relpath.replace("/", "__").replace("\\", "__")


def collect_images(source_dir: Path) -> list[Path]:
    """Recursively collect all image files under source_dir."""
    images = []
    for p in sorted(source_dir.rglob("*")):
        if p.is_file() and p.suffix.lower() in IMAGE_EXTENSIONS:
            images.append(p)
    return images


def create_thumbnail(source_path: Path, thumb_path: Path) -> tuple[int, int] | None:
    """Create a thumbnail. Returns (width, height) or None on failure."""
    try:
        img = Image.open(source_path)
        width, height = img.size

        if width > MAX_DIMENSION or height > MAX_DIMENSION:
            return None

        img.thumbnail((THUMBNAIL_MAX_SIZE, THUMBNAIL_MAX_SIZE), Image.Resampling.LANCZOS)

        # Preserve format: PNG for PNG sources (keeps transparency), JPEG for everything else
        if source_path.suffix.lower() == ".png":
            img.save(thumb_path, format="PNG")
        else:
            img.save(thumb_path, format="JPEG", quality=80)

        return (width, height)
    except Exception:
        return None


def load_relpaths_from_jsonl(path: Path, key: str = "relpath") -> set[str]:
    """Load the set of relpaths from a JSONL file."""
    result = set()
    if path.exists():
        for line in path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if line:
                try:
                    entry = json.loads(line)
                    result.add(entry[key])
                except (json.JSONDecodeError, KeyError):
                    pass
    return result


def load_template(name: str) -> str:
    """Load a template file from the same directory as this script."""
    template_path = Path(__file__).parent / name
    return template_path.read_text(encoding="utf-8") if template_path.exists() else ""


def load_batch_relpaths(batch_path: Path) -> list[str]:
    """Load relative paths from a batch file."""
    return [
        line.strip() for line in batch_path.read_text(encoding="utf-8").splitlines() if line.strip()
    ]


def sample_images_stratified(
    source_dir: Path, all_images: list[Path], target: int
) -> list[Path]:
    """Sample images stratified by top-level folder with inverse-sqrt weighting.

    Small folders get higher sampling rates, but not 100% unless they're tiny
    relative to the overall target. Uses inverse-sqrt weighting for a smooth scale.

    Args:
        source_dir: The root directory images were collected from
        all_images: List of all image Path objects
        target: Target number of images to sample

    Returns:
        List of sampled image paths (not shuffled yet)
    """
    # Group images by top-level folder
    folder_groups: dict[str, list[Path]] = {}
    for img_path in all_images:
        relpath = img_path.relative_to(source_dir)
        # Top-level folder is the first part of the path
        if relpath.parent == Path("."):
            folder_name = "ROOT"
        else:
            folder_name = relpath.parts[0]

        if folder_name not in folder_groups:
            folder_groups[folder_name] = []
        folder_groups[folder_name].append(img_path)

    # Compute weights (inverse-sqrt of folder size)
    folder_names = sorted(folder_groups.keys())
    weights: dict[str, float] = {}
    for folder_name in folder_names:
        count = len(folder_groups[folder_name])
        weights[folder_name] = 1.0 / (count ** 0.5)

    total_weight = sum(weights.values())

    # Compute initial quotas
    quotas: dict[str, int] = {}
    for folder_name in folder_names:
        quota = round(target * weights[folder_name] / total_weight)
        quotas[folder_name] = quota

    # Cap quotas and track if capped
    capped: set[str] = set()
    for folder_name in folder_names:
        actual_count = len(folder_groups[folder_name])
        if quotas[folder_name] > actual_count:
            capped.add(folder_name)
            quotas[folder_name] = actual_count

    # Redistribute surplus from capped folders
    while capped:
        surplus = sum(len(folder_groups[f]) - quotas[f] for f in capped)
        uncapped_folders = [f for f in folder_names if f not in capped]

        if not uncapped_folders or surplus == 0:
            break

        uncapped_weight = sum(weights[f] for f in uncapped_folders)
        new_capped: set[str] = set()

        for folder_name in uncapped_folders:
            extra = round(surplus * weights[folder_name] / uncapped_weight)
            quotas[folder_name] += extra

            actual_count = len(folder_groups[folder_name])
            if quotas[folder_name] > actual_count:
                new_capped.add(folder_name)
                quotas[folder_name] = actual_count

        if not new_capped or new_capped == capped:
            break
        capped = new_capped

    # Sample from each folder
    sampled: list[Path] = []
    for folder_name in folder_names:
        folder_images = folder_groups[folder_name]
        quota = quotas[folder_name]
        sampled.extend(random.sample(folder_images, min(quota, len(folder_images))))

    return sampled


# ---------------------------------------------------------------------------
# Subcommands
# ---------------------------------------------------------------------------


def cmd_prepare(args: argparse.Namespace) -> int:
    source_dir = Path(args.source).resolve()
    prep_dir = Path(args.prep_dir)

    if not source_dir.is_dir():
        print(f"Error: source directory does not exist: {source_dir}", file=sys.stderr)
        return 1

    if prep_dir.exists() and not args.force:
        print(
            f"Error: prep directory already exists: {prep_dir}\nUse --force to overwrite.",
            file=sys.stderr,
        )
        return 1

    # Create directory structure
    thumb_dir = prep_dir / "thumbnails"
    batch_dir = prep_dir / "batches"
    thumb_dir.mkdir(parents=True, exist_ok=True)
    batch_dir.mkdir(parents=True, exist_ok=True)

    # Collect all images recursively
    all_images = collect_images(source_dir)
    print(f"Found {len(all_images)} images in {source_dir}")

    # Apply stratified sampling if requested
    sample_target = getattr(args, "sample", None)
    if sample_target and sample_target > 0:
        all_images = sample_images_stratified(source_dir, all_images, sample_target)
        print(f"Sampled {len(all_images)} images (target: {sample_target})")
        sampled = True
    else:
        sampled = False

    # Process each image
    valid_relpaths: list[str] = []
    skipped: list[tuple[str, str]] = []

    for img_path in all_images:
        relpath = img_path.relative_to(source_dir).as_posix()
        thumb_name = relpath_to_thumbnail_name(relpath)

        # Preserve original extension for the thumbnail
        thumb_path = thumb_dir / thumb_name

        result = create_thumbnail(img_path, thumb_path)
        if result is None:
            # Determine reason
            try:
                img = Image.open(img_path)
                w, h = img.size
                if w > MAX_DIMENSION or h > MAX_DIMENSION:
                    reason = f"dimensions {w}x{h} exceed {MAX_DIMENSION}px limit"
                else:
                    reason = "unknown error during thumbnail creation"
            except Exception as e:
                reason = f"PIL read error: {e}"

            skipped.append((relpath, reason))
            print(f"  [SKIP] {relpath}: {reason}")
        else:
            valid_relpaths.append(relpath)
            print(f"  [OK] {relpath}")

    # Shuffle before batching to mix images from different groups
    random.shuffle(valid_relpaths)

    # Write batch files
    num_batches = 0
    for i in range(0, len(valid_relpaths), BATCH_SIZE):
        batch = valid_relpaths[i : i + BATCH_SIZE]
        num_batches += 1
        batch_path = batch_dir / f"batch-{num_batches:03d}.txt"
        batch_path.write_text("\n".join(batch) + "\n", encoding="utf-8")

    # Write config
    config = {
        "source_dir": str(source_dir),
        "image_count": len(valid_relpaths),
        "skipped_count": len(skipped),
        "batch_count": num_batches,
        "batch_size": BATCH_SIZE,
        "sampled": sampled,
        "created_at": datetime.now(UTC).isoformat(),
    }
    if sampled and sample_target:
        config["sample_target"] = sample_target
    (prep_dir / "config.json").write_text(json.dumps(config, indent=2) + "\n", encoding="utf-8")

    # Write skipped list
    skipped_path = prep_dir / "skipped.txt"
    if skipped:
        lines = [f"{relpath}: {reason}" for relpath, reason in skipped]
        skipped_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    else:
        skipped_path.write_text("No images skipped.\n", encoding="utf-8")

    print("\nPrepare complete:")
    print(f"  Valid images: {len(valid_relpaths)}")
    print(f"  Skipped: {len(skipped)}")
    print(f"  Batches: {num_batches}")
    print(f"  Prep dir: {prep_dir}")
    return 0


def cmd_init(args: argparse.Namespace) -> int:
    prep_dir = Path(args.prep_dir)
    run_dir = Path(args.run_dir)

    if not prep_dir.exists():
        print(f"Error: prep directory does not exist: {prep_dir}", file=sys.stderr)
        return 1

    config_path = prep_dir / "config.json"
    if not config_path.exists():
        print(f"Error: no config.json found in {prep_dir}", file=sys.stderr)
        return 1

    if run_dir.exists():
        print(f"Error: run directory already exists: {run_dir}", file=sys.stderr)
        return 1

    config = json.loads(config_path.read_text(encoding="utf-8"))

    # Create run directory
    run_dir.mkdir(parents=True)

    # Create empty labels and uncertain files
    (run_dir / "labels.jsonl").write_text("", encoding="utf-8")
    (run_dir / "uncertain.jsonl").write_text("", encoding="utf-8")

    # Generate instructions from template
    template = load_template("labeling-instructions.md")
    if not template:
        print("Warning: no labeling-instructions.md template found", file=sys.stderr)
        template = "# Labeling Instructions\n\nNo template found. See the plan for details.\n"

    # Bake in the paths
    instructions = template.replace("{prep-dir}", str(prep_dir))
    instructions = instructions.replace("{run-dir}", str(run_dir))
    instructions = instructions.replace("{source-dir}", config.get("source_dir", "UNKNOWN"))

    (run_dir / "instructions.md").write_text(instructions, encoding="utf-8")

    print("Initialized labeling run:")
    print(f"  Run dir: {run_dir}")
    print(f"  Prep dir: {prep_dir}")
    print(f"  Source: {config.get('source_dir', 'UNKNOWN')}")
    print(f"  Images: {config.get('image_count', 'UNKNOWN')}")
    print("\nNext step: give an agent this prompt:")
    print(f'  "Read {run_dir}/instructions.md and follow the instructions"')
    return 0


def cmd_init_review(args: argparse.Namespace) -> int:
    prep_dir = Path(args.prep_dir)
    source_run = Path(args.source_run)
    review_dir = Path(args.review_dir)

    if not prep_dir.exists():
        print(f"Error: prep directory does not exist: {prep_dir}", file=sys.stderr)
        return 1

    source_labels = source_run / "labels.jsonl"
    if not source_labels.exists() or source_labels.stat().st_size == 0:
        print(f"Error: source run has no labels: {source_labels}", file=sys.stderr)
        return 1

    if review_dir.exists():
        print(f"Error: review directory already exists: {review_dir}", file=sys.stderr)
        return 1

    config_path = prep_dir / "config.json"
    config = json.loads(config_path.read_text(encoding="utf-8"))

    # Create review directory
    review_dir.mkdir(parents=True)

    # Copy original labels as read-only reference
    import shutil

    shutil.copy2(source_labels, review_dir / "original-labels.jsonl")

    # Create empty output files
    (review_dir / "approved.jsonl").write_text("", encoding="utf-8")
    (review_dir / "corrections.jsonl").write_text("", encoding="utf-8")

    # Generate review instructions
    template = load_template("review-instructions.md")
    if not template:
        print("Warning: no review-instructions.md template found", file=sys.stderr)
        template = "# Review Instructions\n\nNo template found. See the plan for details.\n"

    instructions = template.replace("{prep-dir}", str(prep_dir))
    instructions = instructions.replace("{review-dir}", str(review_dir))
    instructions = instructions.replace("{source-dir}", config.get("source_dir", "UNKNOWN"))
    (review_dir / "instructions.md").write_text(instructions, encoding="utf-8")

    label_count = len(load_relpaths_from_jsonl(review_dir / "original-labels.jsonl"))
    print("Initialized review run:")
    print(f"  Review dir: {review_dir}")
    print(f"  Source run: {source_run}")
    print(f"  Labels to review: {label_count}")
    print("\nNext step: give an agent this prompt:")
    print(f'  "Read {review_dir}/instructions.md and follow the instructions"')
    return 0


def cmd_status(args: argparse.Namespace) -> int:
    prep_dir = Path(args.prep_dir)
    review_dir = getattr(args, "review_dir", None)

    if not prep_dir.exists():
        print(f"Error: prep directory does not exist: {prep_dir}", file=sys.stderr)
        return 1

    config_path = prep_dir / "config.json"
    if not config_path.exists():
        print(f"Error: no config.json found in {prep_dir}", file=sys.stderr)
        return 1

    config = json.loads(config_path.read_text(encoding="utf-8"))

    # Dispatch to review or labeling status
    if review_dir:
        return _status_review(prep_dir, Path(review_dir), config)
    else:
        run_dir = Path(args.run_dir)
        return _status_labeling(prep_dir, run_dir, config)


def _status_labeling(prep_dir: Path, run_dir: Path, config: dict) -> int:
    if not run_dir.exists():
        print(f"Error: run directory does not exist: {run_dir}", file=sys.stderr)
        print("Run 'init' first to create a labeling run.", file=sys.stderr)
        return 1

    batch_dir = prep_dir / "batches"
    labeled = load_relpaths_from_jsonl(run_dir / "labels.jsonl")

    # Count uncertain
    uncertain_count = 0
    uncertain_path = run_dir / "uncertain.jsonl"
    if uncertain_path.exists():
        for line in uncertain_path.read_text(encoding="utf-8").splitlines():
            if line.strip():
                uncertain_count += 1

    # Process each batch
    batch_files = sorted(batch_dir.glob("batch-*.txt"))
    total_images = 0
    total_labeled = 0
    next_batch = None
    next_remaining: list[str] = []

    batch_lines: list[str] = []
    for batch_path in batch_files:
        relpaths = load_batch_relpaths(batch_path)
        done = sum(1 for r in relpaths if r in labeled)
        total_images += len(relpaths)
        total_labeled += done

        batch_name = batch_path.stem

        if done == len(relpaths):
            batch_lines.append(f"  {batch_name}: {done}/{len(relpaths)} DONE")
        elif done > 0:
            batch_lines.append(f"  {batch_name}: {done}/{len(relpaths)} incomplete")
            if next_batch is None:
                next_batch = batch_path.name
                next_remaining = [r for r in relpaths if r not in labeled]
        else:
            batch_lines.append(f"  {batch_name}: {done}/{len(relpaths)} pending")
            if next_batch is None:
                next_batch = batch_path.name
                next_remaining = relpaths

    # Print report
    pct = (total_labeled / total_images * 100) if total_images > 0 else 0
    print(f"Prep: {prep_dir} ({config.get('image_count', '?')} images, {len(batch_files)} batches)")
    print(f"Run:  {run_dir}")
    print(f"Progress: {total_labeled}/{total_images} images labeled ({pct:.1f}%)")
    if uncertain_count:
        print(f"Uncertain: {uncertain_count} images flagged for review")
    print()

    for line in batch_lines:
        print(line)

    if next_batch:
        print(f"\nNext: {next_batch}")
        print(f"Remaining in {next_batch}:")
        for r in next_remaining:
            print(f"  {r}")
    elif total_labeled == total_images:
        print("\nAll images labeled!")

    return 0


def _status_review(prep_dir: Path, review_dir: Path, config: dict) -> int:
    if not review_dir.exists():
        print(f"Error: review directory does not exist: {review_dir}", file=sys.stderr)
        return 1

    original = load_relpaths_from_jsonl(review_dir / "original-labels.jsonl")
    approved = load_relpaths_from_jsonl(review_dir / "approved.jsonl")
    corrected = load_relpaths_from_jsonl(review_dir / "corrections.jsonl")
    reviewed = approved | corrected

    total = len(original)
    done = len(reviewed)
    remaining = sorted(original - reviewed)
    pct = (done / total * 100) if total > 0 else 0

    print(f"Prep: {prep_dir} ({config.get('image_count', '?')} images)")
    print(f"Review: {review_dir}")
    print(f"Progress: {done}/{total} labels reviewed ({pct:.1f}%)")
    print(f"  Approved: {len(approved)}")
    print(f"  Corrected: {len(corrected)}")

    if remaining:
        show = remaining[:15]
        print(f"\nNext {len(show)} to review:")
        for r in show:
            print(f"  {r}")
        if len(remaining) > 15:
            print(f"  ... and {len(remaining) - 15} more")
    else:
        print("\nAll labels reviewed!")

    return 0


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Image labeling pipeline: prepare, init, status, and review."
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    # prepare
    p_prepare = subparsers.add_parser("prepare", help="Scan images, create thumbnails and batches")
    p_prepare.add_argument("--source", required=True, help="Source directory containing images")
    p_prepare.add_argument("--prep-dir", required=True, help="Output directory for prep data")
    p_prepare.add_argument(
        "--sample",
        type=int,
        help="Target number of images to sample. If omitted, use all images. "
        "Uses stratified sampling with inverse-sqrt weighting by folder.",
    )
    p_prepare.add_argument("--force", action="store_true", help="Overwrite existing prep directory")

    # init
    p_init = subparsers.add_parser("init", help="Initialize a new labeling run")
    p_init.add_argument("--prep-dir", required=True, help="Path to prep directory")
    p_init.add_argument("--run-dir", required=True, help="Path for the new run directory")

    # init-review
    p_review = subparsers.add_parser("init-review", help="Initialize a review of an existing run")
    p_review.add_argument("--prep-dir", required=True, help="Path to prep directory")
    p_review.add_argument("--source-run", required=True, help="Path to the labeled run to review")
    p_review.add_argument("--review-dir", required=True, help="Path for the new review directory")

    # status
    p_status = subparsers.add_parser("status", help="Show labeling/review progress (read-only)")
    p_status.add_argument("--prep-dir", required=True, help="Path to prep directory")
    p_status.add_argument("--run-dir", help="Path to labeling run directory")
    p_status.add_argument("--review-dir", help="Path to review directory")

    args = parser.parse_args()

    # Validate status args
    if args.command == "status" and not args.run_dir and not args.review_dir:
        parser.error("status requires either --run-dir or --review-dir")

    commands = {
        "prepare": cmd_prepare,
        "init": cmd_init,
        "init-review": cmd_init_review,
        "status": cmd_status,
    }

    # Suppress unused variable warnings for subparser references
    _ = p_prepare, p_init, p_review, p_status

    return commands[args.command](args)


if __name__ == "__main__":
    sys.exit(main())
