"""PyInstaller entry point for Scene Atlas backend sidecar.

Sets environment variables BEFORE importing any backend.app modules,
because importing config.py immediately constructs Settings() and
computes all derived paths from data_dir / images_dir.

Includes crash supervision: if uvicorn crashes, it restarts with
exponential backoff. Gives up after 10 crashes in 5 minutes and exits
with code 1 so Electron can show a fatal error dialog.

Prints SCENE_ATLAS_READY once uvicorn is listening; Electron waits for it.
With --parent-pid, shuts down when Electron is gone (see parent_watchdog.py).
"""

import argparse
import logging
import os
import sys
import time

MAX_RESTARTS = 10
WINDOW_SECS = 300
MAX_BACKOFF = 30
STARTUP_FAILURE = 3  # uvicorn's exit code when startup fails
# The library check refused the folders; Electron offers to choose others (library-setup.md).
LIBRARY_REFUSED = 4

# Bundled modules the app never imports, which may fail outside their intended use.
SELF_CHECK_SKIP: set[str] = set()


def self_check() -> int:
    """Import every bundled top-level module of the runtime dependencies.

    Run by scripts/build/smoke_sidecar.py. Startup only imports what startup needs; this
    catches what fails in the frozen build on other paths (model downloads, video, ...),
    such as a package reading its own metadata at import when the metadata wasn't bundled.
    The spec lists the modules at build time (self_check_modules.json). Third-party only:
    stdlib modules can have side effects on import.
    """
    import importlib
    import json
    import pkgutil
    from pathlib import Path

    listed = Path(sys._MEIPASS, "self_check_modules.json")  # pyright: ignore[reportAttributeAccessIssue]
    expected = set(json.loads(listed.read_text(encoding="utf-8")))
    bundled = {m.name for m in pkgutil.iter_modules()}
    names = sorted((expected & bundled) - SELF_CHECK_SKIP)
    failures = []
    for name in names:
        try:
            importlib.import_module(name)
        except Exception as exc:
            failures.append(f"  {name}: {type(exc).__name__}: {exc}")
    if failures:
        print(f"SELF-CHECK FAILED: {len(failures)} of {len(names)} modules", *failures, sep="\n")
        return 1
    print(f"SELF-CHECK OK: {len(names)} modules")
    return 0


def main():
    if sys.argv[1:] == ["--self-check"]:
        sys.exit(self_check())

    parser = argparse.ArgumentParser(description="Scene Atlas backend (packaged)")
    parser.add_argument("--port", type=int, required=True, help="Port to bind to")
    parser.add_argument(
        "--app-data-dir",
        type=str,
        required=True,
        help="App data directory (fast storage: DB, index, thumbnails)",
    )
    parser.add_argument(
        "--image-library-dir",
        type=str,
        required=True,
        help="Image library directory (cold storage: originals, backups)",
    )
    parser.add_argument(
        "--linked-library-dir",
        type=str,
        default=None,
        help="The user's own maps folder, read in place (optional; need not exist)",
    )
    parser.add_argument(
        "--parent-pid",
        type=int,
        default=None,
        help="Shut down when this process exits or closes our stdin (set by Electron)",
    )
    args = parser.parse_args()

    # Validate roots exist before importing any backend modules.
    # (Settings.__init__ also validates when validate_roots=True, but we
    # check here first so the error appears before any heavy imports.)
    from pathlib import Path

    for label, dirpath in [
        ("SCENE_ATLAS_DATA_DIR", args.app_data_dir),
        ("SCENE_ATLAS_IMAGES_DIR", args.image_library_dir),
    ]:
        if not Path(dirpath).exists():
            print(f"ERROR: {label} does not exist: {dirpath}", file=sys.stderr)
            sys.exit(1)

    # Must set env vars before any backend.app import triggers Settings()
    os.environ["SCENE_ATLAS_DATA_DIR"] = args.app_data_dir
    os.environ["SCENE_ATLAS_IMAGES_DIR"] = args.image_library_dir
    if args.linked_library_dir:
        os.environ["SCENE_ATLAS_LINKED_LIBRARY_DIR"] = args.linked_library_dir
    else:
        os.environ.pop("SCENE_ATLAS_LINKED_LIBRARY_DIR", None)
    os.environ["SCENE_ATLAS_VALIDATE_ROOTS"] = "1"  # Settings() will raise if roots don't exist
    os.environ["SCENE_ATLAS_API_PORT"] = str(args.port)
    os.environ["SCENE_ATLAS_API_HOST"] = "127.0.0.1"
    os.environ["SCENE_ATLAS_APP_MODE"] = "app"

    from backend.app.logging_config import setup_logging

    setup_logging(Path(args.app_data_dir))

    logger = logging.getLogger(__name__)

    import uvicorn

    import backend.app.main as app_main
    from backend.app.main import app

    class SidecarServer(uvicorn.Server):
        async def startup(self, sockets=None) -> None:
            await super().startup(sockets)
            if self.started:
                print(f"SCENE_ATLAS_READY port={self.config.port}", flush=True)

    server: SidecarServer | None = None
    watchdog = None
    if args.parent_pid is not None:
        from backend.app.parent_watchdog import ParentWatchdog

        def _stop_server() -> None:
            if server is not None:
                server.should_exit = True

        watchdog = ParentWatchdog(_stop_server, parent_pid=args.parent_pid)
        watchdog.start()

    restarts: list[float] = []
    backoff = 1

    # Note: unlike scripts/start.py which uses subprocess restart (full isolation),
    # this restarts uvicorn in-process. Corrupted module-level state (singletons,
    # connection pools) will persist across restarts. This is the correct tradeoff
    # for a PyInstaller bundle where subprocess spawning is unreliable.
    while not (watchdog and watchdog.fired):
        server = SidecarServer(
            uvicorn.Config(app, host="127.0.0.1", port=args.port, proxy_headers=False)
        )
        if watchdog and watchdog.fired:
            break
        try:
            server.run()
            if not server.started:
                sys.exit(LIBRARY_REFUSED if app_main.library_refused else STARTUP_FAILURE)
            break  # Clean exit (e.g. graceful shutdown from Electron)
        except SystemExit:
            # Propagate the code: uvicorn exits non-zero when startup fails (e.g. the
            # port is taken), and Electron reports a non-ready exit to the user. A refused
            # library gets its own code, whichever way uvicorn stopped.
            if app_main.library_refused:
                sys.exit(LIBRARY_REFUSED)
            raise
        except Exception:
            now = time.time()
            restarts = [t for t in restarts if now - t < WINDOW_SECS]

            if len(restarts) >= MAX_RESTARTS:
                logger.critical(
                    "Backend crashed %d times in %ds — giving up",
                    MAX_RESTARTS,
                    WINDOW_SECS,
                )
                sys.exit(1)

            restarts.append(now)
            logger.exception(
                "Backend crashed, restarting in %ds (crash %d/%d in window)",
                backoff,
                len(restarts),
                MAX_RESTARTS,
            )
            time.sleep(backoff)
            backoff = min(backoff * 2, MAX_BACKOFF)


if __name__ == "__main__":
    main()
