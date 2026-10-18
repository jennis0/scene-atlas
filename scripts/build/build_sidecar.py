"""Build the Scene Atlas backend sidecar with PyInstaller.

PyInstaller runs in its own virtualenv (.venv-sidecar), synced exactly to the
runtime dependencies, one onnxruntime extra and the `sidecar` dependency group.
PyInstaller bundles every module it can import, including optional imports, so
building from the dev venv dragged in IPython, transformers, onnx and the other
dev tools. A package that isn't installed can't be bundled.

PyInstaller writes its --onedir output straight to
backend/pyinstaller/dist/scene-atlas-backend/, which electron-builder's
extraResources config bundles as resources/sidecar/.

ONNX models are NOT bundled — they are downloaded from HuggingFace at
runtime by the model_download_service.

GPU support comes from the onnxruntime variant, chosen with --ort-extra
(design/electron.md#gpu-support-in-desktop-builds).

Usage:
    uv run python scripts/build/build_sidecar.py [--clean] [--ort-extra EXTRA]
"""

import argparse
import os
import platform
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).parent.parent.parent
SPEC = ROOT / "backend" / "pyinstaller" / "scene_atlas_backend.spec"
FRONTEND_DIST = ROOT / "frontend" / "dist"
PYINSTALLER_OUT = ROOT / "backend" / "pyinstaller" / "dist" / "scene-atlas-backend"
SIDECAR_EXE = PYINSTALLER_OUT / (
    "scene-atlas-backend.exe" if sys.platform == "win32" else "scene-atlas-backend"
)
BUILD_VENV = ROOT / ".venv-sidecar"
ORT_EXTRAS = ("cpu", "gpu", "gpu-directml")
# The desktop builds' onnxruntime per platform; the Release matrix passes the same.
DEFAULT_ORT_EXTRA = "gpu-directml" if sys.platform == "win32" else "cpu"


def get_platform_info() -> tuple[str, str]:
    """Return (os_name, arch) for logging."""
    system = platform.system()
    machine = platform.machine().lower()
    arch = "arm64" if machine in ("arm64", "aarch64") else "x86_64"
    return system, arch


def sync_build_venv(ort_extra: str) -> Path:
    """Sync .venv-sidecar to exactly the runtime deps; return its Python."""
    cmd = [
        "uv",
        "sync",
        "--frozen",
        "--no-install-project",
        # A uv-managed CPython, as in CI: never a system one such as the Microsoft
        # Store's, whose file-system virtualisation doesn't belong in a frozen app.
        "--managed-python",
        "--extra",
        ort_extra,
        "--group",
        "sidecar",
    ]
    print(f"Syncing {BUILD_VENV.name}: {' '.join(cmd)}")
    # VIRTUAL_ENV is the dev venv when this script runs under `uv run`; drop it so uv
    # doesn't warn that it differs from UV_PROJECT_ENVIRONMENT.
    env = {k: v for k, v in os.environ.items() if k != "VIRTUAL_ENV"}
    env["UV_PROJECT_ENVIRONMENT"] = str(BUILD_VENV)
    result = subprocess.run(cmd, cwd=str(ROOT), env=env, check=False)
    if result.returncode != 0:
        sys.exit(f"uv sync for {BUILD_VENV.name} failed")
    scripts = "Scripts" if sys.platform == "win32" else "bin"
    return BUILD_VENV / scripts / ("python.exe" if sys.platform == "win32" else "python")


def main() -> None:
    parser = argparse.ArgumentParser(description="Build Scene Atlas backend sidecar")
    parser.add_argument(
        "--clean", action="store_true", help="Remove previous build before building"
    )
    parser.add_argument(
        "--ort-extra",
        choices=ORT_EXTRAS,
        default=DEFAULT_ORT_EXTRA,
        help=f"onnxruntime variant to bundle (default here: {DEFAULT_ORT_EXTRA})",
    )
    args = parser.parse_args()

    if not (FRONTEND_DIST / "index.html").exists():
        sys.exit(f"{FRONTEND_DIST} not found: build the frontend first (the sidecar serves it)")

    system, arch = get_platform_info()
    print(f"Building sidecar for {system} {arch} with onnxruntime extra '{args.ort_extra}'")

    if args.clean and PYINSTALLER_OUT.exists():
        print(f"Cleaning {PYINSTALLER_OUT}")
        shutil.rmtree(PYINSTALLER_OUT)

    build_dir = ROOT / "backend" / "pyinstaller" / "build"
    if args.clean and build_dir.exists():
        shutil.rmtree(build_dir)

    python = sync_build_venv(args.ort_extra)
    cmd = [
        str(python),
        "-m",
        "PyInstaller",
        "--noconfirm",
        "--distpath",
        str(PYINSTALLER_OUT.parent),
        "--workpath",
        str(build_dir),
        str(SPEC),
    ]

    print(f"Running: {' '.join(cmd)}")
    result = subprocess.run(cmd, cwd=str(ROOT), check=False)

    if result.returncode != 0:
        print("PyInstaller build failed", file=sys.stderr)
        sys.exit(result.returncode)

    if not PYINSTALLER_OUT.exists():
        print(f"Expected output directory not found: {PYINSTALLER_OUT}", file=sys.stderr)
        sys.exit(1)

    if not SIDECAR_EXE.exists():
        print(f"Main executable not found at: {SIDECAR_EXE}", file=sys.stderr)
        sys.exit(1)

    print(f"\nSidecar built successfully: {PYINSTALLER_OUT}")
    print(f"Main executable: {SIDECAR_EXE}")
    print("Ready for: npm run electron:build")


if __name__ == "__main__":
    main()
