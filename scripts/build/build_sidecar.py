"""Build the Scene Atlas backend sidecar with PyInstaller.

PyInstaller writes its --onedir output straight to
backend/pyinstaller/dist/scene-atlas-backend/, which electron-builder's
extraResources config bundles as resources/sidecar/.

ONNX models are NOT bundled — they are downloaded from HuggingFace at
runtime by the model_download_service.

GPU support is determined by which onnxruntime variant is installed in the
venv at build time (onnxruntime, onnxruntime-directml, etc.) — there is no
separate GPU build step.

Usage:
    uv run python scripts/build/build_sidecar.py [--clean]
"""

import argparse
import platform
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).parent.parent.parent
SPEC = ROOT / "backend" / "pyinstaller" / "scene_atlas_backend.spec"
PYINSTALLER_OUT = ROOT / "backend" / "pyinstaller" / "dist" / "scene-atlas-backend"
SIDECAR_EXE = PYINSTALLER_OUT / (
    "scene-atlas-backend.exe" if sys.platform == "win32" else "scene-atlas-backend"
)


def get_platform_info() -> tuple[str, str]:
    """Return (os_name, arch) for logging."""
    system = platform.system()
    machine = platform.machine().lower()
    arch = "arm64" if machine in ("arm64", "aarch64") else "x86_64"
    return system, arch


def main() -> None:
    parser = argparse.ArgumentParser(description="Build Scene Atlas backend sidecar")
    parser.add_argument(
        "--clean", action="store_true", help="Remove previous build before building"
    )
    args = parser.parse_args()

    system, arch = get_platform_info()
    print(f"Building sidecar for {system} {arch}")

    if args.clean and PYINSTALLER_OUT.exists():
        print(f"Cleaning {PYINSTALLER_OUT}")
        shutil.rmtree(PYINSTALLER_OUT)

    build_dir = ROOT / "backend" / "pyinstaller" / "build"
    if args.clean and build_dir.exists():
        shutil.rmtree(build_dir)

    cmd = [
        sys.executable,
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
