"""Build Scene Atlas as an Electron desktop app.

Usage:
    uv run python scripts/build_electron.py [options]

Options:
    --skip-sidecar    Skip PyInstaller build (reuse existing sidecar)
    --skip-frontend   Skip Vite build (reuse existing frontend/dist)
    --clean           Remove previous build outputs before building
    --no-package      Stop after compiling — skip electron-builder step
    --dev             Quick dev build: unpack only, no installer (skips slow NSIS compression)
"""

import argparse
import shutil
import subprocess
import sys
from pathlib import Path

# Force UTF-8 output on Windows (avoids cp1252 UnicodeEncodeError)
if sys.stdout.encoding.lower() != 'utf-8':
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')  # type: ignore[attr-defined]
if sys.stderr.encoding.lower() != 'utf-8':
    sys.stderr.reconfigure(encoding='utf-8', errors='replace')  # type: ignore[attr-defined]

ROOT = Path(__file__).parent.parent

# ── Terminal colours (enable VT on Windows, skip gracefully if unsupported) ─
class C:
    try:
        import ctypes
        ctypes.windll.kernel32.SetConsoleMode(  # type: ignore[attr-defined]
            ctypes.windll.kernel32.GetStdHandle(-11), 7  # type: ignore[attr-defined]
        )
        RED    = '\033[0;31m'
        GREEN  = '\033[0;32m'
        YELLOW = '\033[1;33m'
        CYAN   = '\033[0;36m'
        BOLD   = '\033[1m'
        RESET  = '\033[0m'
    except Exception:
        RED = GREEN = YELLOW = CYAN = BOLD = RESET = ''

def info(msg):    print(f"{C.CYAN}>{C.RESET} {msg}")
def success(msg): print(f"{C.GREEN}OK{C.RESET} {msg}")
def warn(msg):    print(f"{C.YELLOW}!{C.RESET}  {msg}")
def step(msg):    print(f"\n{C.BOLD}-- {msg}{C.RESET}")
def die(msg):     print(f"{C.RED}FAIL{C.RESET} {msg}", file=sys.stderr); sys.exit(1)

def run(*cmd: str, cwd: Path = ROOT, check: bool = True) -> subprocess.CompletedProcess:
    """Run a command, streaming output, raising on failure."""
    # On Windows, .cmd scripts (npm, npx) require shell=True or the .cmd suffix
    result = subprocess.run(cmd, cwd=str(cwd), check=False,
                            shell=(sys.platform == "win32"))
    if check and result.returncode != 0:
        die(f"Command failed (exit {result.returncode}): {' '.join(cmd)}")
    return result

def npm(*args: str, cwd: Path = ROOT) -> None:
    run("npm", *args, cwd=cwd)

def npx(*args: str, cwd: Path = ROOT) -> None:
    run("npx", *args, cwd=cwd)

def dir_size(path: Path) -> str:
    total = sum(f.stat().st_size for f in path.rglob('*') if f.is_file())
    for unit in ('B', 'KB', 'MB', 'GB'):
        if total < 1024:
            return f"{total:.0f} {unit}"
        total /= 1024
    return f"{total:.1f} TB"


def main() -> None:
    parser = argparse.ArgumentParser(description="Build Scene Atlas Electron app")
    parser.add_argument("--skip-sidecar",  action="store_true", help="Reuse existing PyInstaller sidecar")
    parser.add_argument("--skip-frontend", action="store_true", help="Reuse existing frontend/dist")
    parser.add_argument("--clean",         action="store_true", help="Clean previous outputs first")
    parser.add_argument("--no-package",    action="store_true", help="Skip electron-builder packaging")
    parser.add_argument("--dev",           action="store_true", help="Quick dev build: unpack only, no installer (skips slow NSIS compression)")
    args = parser.parse_args()

    print(f"\n{C.BOLD}Scene Atlas — Electron build{C.RESET}")
    print(f"Root: {ROOT}\n")

    # ── Prerequisites ────────────────────────────────────────────────────────
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

    # ── Clean ────────────────────────────────────────────────────────────────
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

    # ── Step 1: Python sidecar ───────────────────────────────────────────────
    if args.skip_sidecar:
        warn("Skipping sidecar build (--skip-sidecar)")
        sidecar_dir = ROOT / "backend" / "pyinstaller" / "dist" / "scene-atlas-backend"
        if not sidecar_dir.exists():
            die(f"Sidecar not found at {sidecar_dir} — run without --skip-sidecar first")
        success(f"Using existing sidecar ({dir_size(sidecar_dir)})")
    else:
        step("Building Python sidecar (PyInstaller)")
        info("This may take several minutes on first build...")
        run("uv", "run", "python", "scripts/build_sidecar.py")

        sidecar_dir = ROOT / "backend" / "pyinstaller" / "dist" / "scene-atlas-backend"
        exe = sidecar_dir / ("scene-atlas-backend.exe" if sys.platform == "win32" else "scene-atlas-backend")
        if not exe.exists():
            die(f"Sidecar executable not found after build: {exe}")
        success(f"Sidecar built ({dir_size(sidecar_dir)})")

    # ── Step 2: Frontend ─────────────────────────────────────────────────────
    if args.skip_frontend:
        warn("Skipping frontend build (--skip-frontend)")
        if not (ROOT / "frontend" / "dist").exists():
            die("frontend/dist not found — run without --skip-frontend first")
        success("Using existing frontend build")
    else:
        step("Building frontend (Vite)")
        npm("run", "build", "--prefix", "frontend")
        success("Frontend built")

    # ── Step 3: Compile Electron TypeScript ──────────────────────────────────
    step("Compiling Electron main process (TypeScript)")
    npx("tsc", "-p", "electron/tsconfig.json")
    success("Electron TS compiled")

    # ── Step 4: Package ──────────────────────────────────────────────────────
    if args.no_package:
        warn("Skipping packaging (--no-package)")
    elif args.dev:
        step("Packaging with electron-builder (dev: dir only, no installer)")
        info("Skipping NSIS compression — run dist-electron/win-unpacked/Scene Atlas.exe to test")
        npx("electron-builder", "--publish", "never", "--win", "dir")
        exe = ROOT / "dist-electron" / "win-unpacked" / "Scene Atlas.exe"
        if exe.exists():
            print()
            success(f"Dev build ready: {exe.relative_to(ROOT)}")
    else:
        step("Packaging with electron-builder")
        npx("electron-builder", "--publish", "never")

        out = ROOT / "dist-electron"
        if out.exists():
            installers = [
                f for f in out.iterdir()
                if f.suffix in ('.exe', '.msi', '.dmg', '.AppImage', '.deb')
            ]
            if installers:
                print()
                success(f"Build complete. Installers in dist-electron/:")
                for f in sorted(installers):
                    size = f.stat().st_size / (1024 * 1024)
                    print(f"   {f.name}  ({size:.0f} MB)")

    print(f"\n{C.GREEN}{C.BOLD}Done.{C.RESET}\n")


if __name__ == "__main__":
    main()
