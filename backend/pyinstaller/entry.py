"""PyInstaller entry point for Scene Atlas backend sidecar.

Sets environment variables BEFORE importing any backend.app modules,
because importing config.py immediately constructs Settings() and
computes all derived paths from app_data_dir / image_library_dir.

Includes crash supervision: if uvicorn crashes, it restarts with
exponential backoff. Gives up after 10 crashes in 5 minutes and exits
with code 1 so Electron can show a fatal error dialog.
"""

import argparse
import logging
import os
import sys
import time

MAX_RESTARTS = 10
WINDOW_SECS = 300
MAX_BACKOFF = 30


def main():
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
    args = parser.parse_args()

    # Validate roots exist before importing any backend modules.
    # (Settings.__init__ also validates when validate_roots=True, but we
    # check here first so the error appears before any heavy imports.)
    from pathlib import Path

    for label, dirpath in [
        ("APP_DATA_DIR", args.app_data_dir),
        ("IMAGE_LIBRARY_DIR", args.image_library_dir),
    ]:
        if not Path(dirpath).exists():
            print(f"ERROR: {label} does not exist: {dirpath}", file=sys.stderr)
            sys.exit(1)

    # Must set env vars before any backend.app import triggers Settings()
    os.environ["APP_DATA_DIR"] = args.app_data_dir
    os.environ["IMAGE_LIBRARY_DIR"] = args.image_library_dir
    os.environ["VALIDATE_ROOTS"] = "1"  # Settings() will raise if roots don't exist
    os.environ["API_PORT"] = str(args.port)
    os.environ["API_HOST"] = "127.0.0.1"
    os.environ["APP_MODE"] = "app"

    from backend.app.logging_config import setup_logging

    setup_logging(Path(args.app_data_dir))

    logger = logging.getLogger(__name__)

    import uvicorn

    from backend.app.main import app  # noqa: E402

    restarts: list[float] = []
    backoff = 1

    # Note: unlike scripts/start.py which uses subprocess restart (full isolation),
    # this restarts uvicorn in-process. Corrupted module-level state (singletons,
    # connection pools) will persist across restarts. This is the correct tradeoff
    # for a PyInstaller bundle where subprocess spawning is unreliable.
    while True:
        try:
            uvicorn.run(app, host="127.0.0.1", port=args.port)
            break  # Clean exit (e.g. graceful shutdown from Electron)
        except SystemExit:
            # Propagate the code: uvicorn exits non-zero when startup fails (e.g. the
            # port is taken), and Electron reports a non-ready exit to the user.
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
