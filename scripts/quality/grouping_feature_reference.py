"""Regenerate the grouping-feature parity references from the research code.

Scene Atlas's ``phash256`` and ``edge_descriptor`` (backend/pipeline/grouping_features.py)
must equal the features the variant-grouping research was calibrated on (ADR-028,
design/variant-grouping.md §4). This computes them on the test fixtures
(backend/tests/unit/grouping_fixtures.py) with scene-atlas-learning's own code:

- the research thumbnail step (``preprocessing.thumbnails.generate_thumbnail``: alpha
  flattened onto white, RGB), then
- ``preprocessing.hashing.compute_phash`` (``imagehash.phash(hash_size=16)``), and
- ``classbench.layout_features._describe`` (the edge map), on a lossless PNG of that
  thumbnail.

Run it with the research environment's Python, which has ``imagehash``; Scene Atlas
doesn't depend on it:

    /path/to/scene-atlas-learning/.venv/bin/python \\
        scripts/quality/grouping_feature_reference.py /path/to/scene-atlas-learning
"""

from __future__ import annotations

import base64
import importlib.util
import json
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
FIXTURES = ROOT / "backend" / "tests" / "unit" / "grouping_fixtures.py"
OUTPUT = ROOT / "backend" / "tests" / "unit" / "grouping_features_reference.json"


def _load_fixtures():
    spec = importlib.util.spec_from_file_location("grouping_fixtures", FIXTURES)
    if spec is None or spec.loader is None:
        raise ImportError(FIXTURES)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.FIXTURES


def main(research_root: Path) -> None:
    sys.path.insert(0, str(research_root))
    import imagehash
    import numpy as np
    import PIL
    import scipy
    from classbench.layout_features import _describe
    from preprocessing.hashing import compute_phash
    from preprocessing.thumbnails import generate_thumbnail

    references = {}
    with tempfile.TemporaryDirectory() as tmp:
        for name, build in _load_fixtures().items():
            thumb = generate_thumbnail(build(), Path(tmp) / f"{name}.webp")
            png = Path(tmp) / f"{name}.png"
            thumb.save(png)  # lossless: the descriptor sees exactly the thumbnail's pixels
            described = _describe(str(png))  # an absolute path ignores PROCESSED_DIR
            if described is None:
                raise RuntimeError(f"The research descriptor couldn't read {name}")
            edge = described[2].astype("<f2")
            references[name] = {
                "phash256": compute_phash(thumb),
                "edge_f16_base64": base64.b64encode(edge.tobytes()).decode(),
            }
    OUTPUT.write_text(
        json.dumps(
            {
                "generated_with": {
                    "imagehash": imagehash.__version__,
                    "numpy": np.__version__,
                    "pillow": PIL.__version__,
                    "scipy": scipy.__version__,
                },
                "fixtures": references,
            },
            indent=2,
        )
        + "\n"
    )
    print(f"Wrote {len(references)} references to {OUTPUT}")


if __name__ == "__main__":
    if len(sys.argv) != 2:
        sys.exit(__doc__)
    main(Path(sys.argv[1]).resolve())
