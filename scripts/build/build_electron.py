"""Build Scene Atlas as an Electron desktop app.

Usage:
    uv run python scripts/build/build_electron.py [options]

Options:
    --skip-sidecar    Skip PyInstaller build (reuse existing sidecar)
    --skip-frontend   Skip Vite build (reuse existing frontend/dist)
    --clean           Remove previous build outputs before building
    --no-package      Stop after compiling — skip electron-builder step
    --dev             Quick dev build: unpack only, no installer (skips slow NSIS compression)
    --platform        Target platform: windows, macos, linux, or current (default: current)
                      Note: macOS builds require a macOS host for code signing/notarisation.
    --publish         Pass --publish always to electron-builder (for CI releases)
"""

import argparse
import shutil
import subprocess
import sys
from pathlib import Path

from build_sidecar import PYINSTALLER_OUT, ROOT, SIDECAR_EXE

# Force UTF-8 output on Windows (avoids cp1252 UnicodeEncodeError)
if sys.stdout.encoding.lower() != "utf-8":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[attr-defined]
if sys.stderr.encoding.lower() != "utf-8":
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[attr-defined]


def _supports_colour() -> bool:
    if not sys.stdout.isatty():
        return False
    if sys.platform != "win32":
        return True
    # Windows consoles render ANSI codes only once VT processing is enabled.
    try:
        import ctypes

        kernel32 = ctypes.windll.kernel32  # type: ignore[attr-defined]
        return bool(kernel32.SetConsoleMode(kernel32.GetStdHandle(-11), 7))
    except (AttributeError, OSError):
        return False


_COLOUR = _supports_colour()


class C:
    RED = "\033[0;31m" if _COLOUR else ""
    GREEN = "\033[0;32m" if _COLOUR else ""
    YELLOW = "\033[1;33m" if _COLOUR else ""
    CYAN = "\033[0;36m" if _COLOUR else ""
    BOLD = "\033[1m" if _COLOUR else ""
    RESET = "\033[0m" if _COLOUR else ""


def info(msg):
    print(f"{C.CYAN}>{C.RESET} {msg}")


def success(msg):
    print(f"{C.GREEN}OK{C.RESET} {msg}")


def warn(msg):
    print(f"{C.YELLOW}!{C.RESET}  {msg}")


def step(msg):
    print(f"\n{C.BOLD}-- {msg}{C.RESET}")


def die(msg):
    print(f"{C.RED}FAIL{C.RESET} {msg}", file=sys.stderr)
    sys.exit(1)


def run(*cmd: str, cwd: Path = ROOT, check: bool = True) -> subprocess.CompletedProcess:
    """Run a command, streaming output, raising on failure."""
    # On Windows, .cmd scripts (npm, npx) require shell=True or the .cmd suffix
    result = subprocess.run(cmd, cwd=str(cwd), check=False, shell=(sys.platform == "win32"))
    if check and result.returncode != 0:
        die(f"Command failed (exit {result.returncode}): {' '.join(cmd)}")
    return result


def npm(*args: str, cwd: Path = ROOT) -> None:
    run("npm", *args, cwd=cwd)


def npx(*args: str, cwd: Path = ROOT) -> None:
    run("npx", *args, cwd=cwd)


def dir_size(path: Path) -> str:
    total = sum(f.stat().st_size for f in path.rglob("*") if f.is_file())
    for unit in ("B", "KB", "MB", "GB"):
        if total < 1024:
            return f"{total:.0f} {unit}"
        total /= 1024
    return f"{total:.1f} TB"


def main() -> None:
    parser = argparse.ArgumentParser(description="Build Scene Atlas Electron app")
    parser.add_argument(
        "--skip-sidecar", action="store_true", help="Reuse existing PyInstaller sidecar"
    )
    parser.add_argument("--skip-frontend", action="store_true", help="Reuse existing frontend/dist")
    parser.add_argument("--clean", action="store_true", help="Clean previous outputs first")
    parser.add_argument("--no-package", action="store_true", help="Skip electron-builder packaging")
    parser.add_argument(
        "--dev",
        action="store_true",
        help="Quick dev build: unpack only, no installer (skips slow NSIS compression)",
    )
    parser.add_argument(
        "--platform",
        choices=["windows", "macos", "linux", "current"],
        default="current",
        help="Target platform (default: current OS). macOS builds require a macOS host.",
    )
    parser.add_argument(
        "--publish",
        action="store_true",
        help="Publish to GitHub Releases (passes --publish always to electron-builder)",
    )
    args = parser.parse_args()

    platform_label = args.platform if args.platform != "current" else f"current ({sys.platform})"
    print(f"\n{C.BOLD}Scene Atlas — Electron build ({platform_label}){C.RESET}")
    print(f"Root: {ROOT}\n")

    step("Checking prerequisites")

    if not shutil.which("uv"):
        die("uv not found. Install from https://docs.astral.sh/uv/")
    if not shutil.which("npm"):
        die("npm not found. Install Node.js from https://nodejs.org/")

    if not (ROOT / "node_modules").exists():
        info("Installing root Node dependencies...")
        npm("install")

    if not (ROOT / "frontend" / "node_modules").exists():
        info("Installing frontend Node dependencies...")
        npm("install", "--prefix", "frontend")

    success("Prerequisites OK")

    if args.clean:
        step("Cleaning previous outputs")
        for d in [
            ROOT / "backend" / "pyinstaller" / "dist",
            ROOT / "backend" / "pyinstaller" / "build",
            ROOT / "electron" / "dist",
            ROOT / "frontend" / "dist",
            ROOT / "dist-electron",
        ]:
            if d.exists():
                info(f"Removing {d.relative_to(ROOT)}")
                shutil.rmtree(d)
        success("Cleaned")

    # The sidecar bundles frontend/dist, so the frontend must be built first.
    if args.skip_frontend:
        warn("Skipping frontend build (--skip-frontend)")
        if not (ROOT / "frontend" / "dist").exists():
            die("frontend/dist not found — run without --skip-frontend first")
        success("Using existing frontend build")
    else:
        step("Building frontend (Vite)")
        npm("run", "build", "--prefix", "frontend")
        success("Frontend built")

    if args.skip_sidecar:
        warn("Skipping sidecar build (--skip-sidecar)")
        if not SIDECAR_EXE.exists():
            die(f"Sidecar not found at {SIDECAR_EXE} — run without --skip-sidecar first")
        success(f"Using existing sidecar ({dir_size(PYINSTALLER_OUT)})")
    else:
        step("Building Python sidecar (PyInstaller)")
        info("This may take several minutes on first build...")
        run("uv", "run", "python", "scripts/build/build_sidecar.py")
        success(f"Sidecar built ({dir_size(PYINSTALLER_OUT)})")

    step("Compiling Electron main process (TypeScript)")
    npx("tsc", "-p", "electron/tsconfig.json")
    success("Electron TS compiled")

    PLATFORM_FLAGS = {
        "windows": "--win",
        "macos": "--mac",
        "linux": "--linux",
        "current": None,  # electron-builder auto-detects
    }
    platform_flag = PLATFORM_FLAGS[args.platform]

    if args.no_package:
        warn("Skipping packaging (--no-package)")
    elif args.dev:
        step("Packaging with electron-builder (dev: unpacked dir only, no installer)")
        cmd = ["electron-builder", "--publish", "never"]
        cmd += [platform_flag, "dir"] if platform_flag else ["--dir"]
        npx(*cmd)
        out = ROOT / "dist-electron"
        unpacked = sorted(
            d
            for d in (out.iterdir() if out.exists() else [])
            if d.is_dir() and (d.name.endswith("-unpacked") or d.name.startswith("mac"))
        )
        if unpacked:
            print()
            success("Dev build ready (unpacked app):")
            for d in unpacked:
                print(f"   {d.relative_to(ROOT)}")
    else:
        publish_value = "always" if args.publish else "never"
        step(f"Packaging with electron-builder (--publish {publish_value})")
        cmd = ["electron-builder", "--publish", publish_value]
        if platform_flag:
            cmd.append(platform_flag)
        npx(*cmd)

        out = ROOT / "dist-electron"
        if out.exists():
            installers = [
                f
                for f in out.iterdir()
                if f.suffix in (".exe", ".msi", ".dmg", ".AppImage", ".deb")
            ]
            if installers:
                print()
                success("Build complete. Installers in dist-electron/:")
                for f in sorted(installers):
                    size = f.stat().st_size / (1024 * 1024)
                    print(f"   {f.name}  ({size:.0f} MB)")

    print(f"\n{C.GREEN}{C.BOLD}Done.{C.RESET}\n")


if __name__ == "__main__":
    main()
