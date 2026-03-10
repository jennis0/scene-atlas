"""Build the Scene Atlas backend sidecar with PyInstaller.

Runs PyInstaller, then copies the --onedir output to the location that
electron-builder's extraResources config expects.

Usage:
    uv run python scripts/build_sidecar.py [--clean]
"""

import argparse
import os
import platform
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).parent.parent
SPEC = ROOT / "backend" / "pyinstaller" / "scene_atlas_backend.spec"
PYINSTALLER_OUT = ROOT / "backend" / "pyinstaller" / "dist" / "scene-atlas-backend"
# electron-builder copies this directory to process.resourcesPath/sidecar/
ELECTRON_RESOURCES = ROOT / "backend" / "pyinstaller" / "dist"

# Model to bundle — matches EMBEDDING_MODEL env var used by the spec file
_EMBEDDING_MODEL = os.environ.get("EMBEDDING_MODEL", "clip-vit-b-32")

# GPU variant — passed through to PyInstaller spec for provider-specific bundling
_GPU_VARIANT = os.environ.get("GPU_VARIANT", "")
# CoreML is opportunistic (no special build handling needed) so it's not a GPU_VARIANT.
_KNOWN_GPU_VARIANTS = {"directml", "cuda"}
_MODELS_DIR = ROOT / "backend" / "models" / _EMBEDDING_MODEL

# ONNX model files that must exist before building
_REQUIRED_ONNX_FILES = [
    _MODELS_DIR / "clip_vision_encoder.onnx",
    _MODELS_DIR / "clip_text_encoder.onnx",
    _MODELS_DIR / "manifest.json",
]


def get_platform_info() -> tuple[str, str]:
    """Return (os_name, arch) for logging."""
    system = platform.system()
    machine = platform.machine().lower()
    arch = "arm64" if machine in ("arm64", "aarch64") else "x86_64"
    return system, arch


def check_onnx_models() -> bool:
    """Verify ONNX model files exist before building."""
    missing = [f for f in _REQUIRED_ONNX_FILES if not f.exists()]
    if missing:
        print("ERROR: Required ONNX model files are missing:", file=sys.stderr)
        for f in missing:
            print(f"  - {f.relative_to(ROOT)}", file=sys.stderr)
        print(
            f"\nRun the export script first:\n  uv run python scripts/export_model_onnx.py"
            f"\n\nActive model: {_EMBEDDING_MODEL} (set EMBEDDING_MODEL env var to change)",
            file=sys.stderr,
        )
        return False
    return True


def _check_directml_provider() -> None:
    """Warn if DmlExecutionProvider is not available in the current onnxruntime."""
    try:
        import onnxruntime

        providers = onnxruntime.get_available_providers()
        if "DmlExecutionProvider" not in providers:
            print(
                "WARNING: GPU_VARIANT=directml but DmlExecutionProvider is not available "
                "in this onnxruntime installation.",
                file=sys.stderr,
            )
            print(
                f"  Available providers: {providers}",
                file=sys.stderr,
            )
            print(
                "  Install onnxruntime-directml to enable DirectML support.",
                file=sys.stderr,
            )
    except ImportError:
        print(
            "WARNING: GPU_VARIANT=directml but onnxruntime is not installed.",
            file=sys.stderr,
        )


def main() -> None:
    parser = argparse.ArgumentParser(description="Build Scene Atlas backend sidecar")
    parser.add_argument(
        "--clean", action="store_true", help="Remove previous build before building"
    )
    args = parser.parse_args()

    system, arch = get_platform_info()
    print(f"Building sidecar for {system} {arch}")
    if _GPU_VARIANT:
        if _GPU_VARIANT not in _KNOWN_GPU_VARIANTS:
            print(
                f"ERROR: Unknown GPU_VARIANT '{_GPU_VARIANT}'. "
                f"Valid values: {', '.join(sorted(_KNOWN_GPU_VARIANTS))}",
                file=sys.stderr,
            )
            sys.exit(1)
        print(f"GPU variant: {_GPU_VARIANT}")
        if _GPU_VARIANT == "cuda":
            print(
                "WARNING: CUDA GPU variant is untested for Electron packaging. "
                "DirectML is recommended for desktop apps.",
                file=sys.stderr,
            )

    # Validate GPU provider availability before building
    if _GPU_VARIANT == "directml":
        _check_directml_provider()

    if not check_onnx_models():
        sys.exit(1)

    if args.clean and PYINSTALLER_OUT.exists():
        print(f"Cleaning {PYINSTALLER_OUT}")
        shutil.rmtree(PYINSTALLER_OUT)

    build_dir = ROOT / "backend" / "pyinstaller" / "build"
    if args.clean and build_dir.exists():
        shutil.rmtree(build_dir)

    # Run PyInstaller via uv
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

    # Build an env dict that passes GPU_VARIANT through to the spec file
    env = os.environ.copy()
    if _GPU_VARIANT:
        env["GPU_VARIANT"] = _GPU_VARIANT

    print(f"Running: {' '.join(cmd)}")
    result = subprocess.run(cmd, cwd=str(ROOT), env=env, check=False)

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
