"""Build the Scene Atlas backend sidecar with PyInstaller.

Runs PyInstaller, then copies the --onedir output to the location that
electron-builder's extraResources config expects.

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
# electron-builder copies this directory to process.resourcesPath/sidecar/
ELECTRON_RESOURCES = ROOT / "backend" / "pyinstaller" / "dist"


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

    # Run PyInstaller
    cmd = [
        sys.executable,
        "-m",
        "PyInstaller",
        "--noconfirm",
        "--distpath",
        str(ROOT / "backend" / "pyinstaller" / "dist"),
        "--workpath",
        str(ROOT / "backend" / "pyinstaller" / "build"),
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

    # Verify the main executable exists
    ext = ".exe" if system == "Windows" else ""
    exe_path = PYINSTALLER_OUT / f"scene-atlas-backend{ext}"
    if not exe_path.exists():
        print(f"Main executable not found at: {exe_path}", file=sys.stderr)
        sys.exit(1)

    print(f"\nSidecar built successfully: {PYINSTALLER_OUT}")
    print(f"Main executable: {exe_path}")
    print(f"\nElectron will bundle from: {ELECTRON_RESOURCES}")
    print("Ready for: npm run electron:build")


if __name__ == "__main__":
    main()
