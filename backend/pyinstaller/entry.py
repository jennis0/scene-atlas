"""PyInstaller entry point for Scene Atlas backend sidecar.

Sets environment variables BEFORE importing any backend.app modules,
because importing config.py immediately constructs Settings() and
computes all derived paths from data_dir.

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
    parser.add_argument("--data-dir", type=str, required=True, help="Data directory path")
    args = parser.parse_args()

    # Must set env vars before any backend.app import triggers Settings()
    os.environ["DATA_DIR"] = args.data_dir
    os.environ["API_PORT"] = str(args.port)
    os.environ["API_HOST"] = "127.0.0.1"
    os.environ["APP_MODE"] = "app"

    from pathlib import Path

    from backend.app.logging_config import setup_logging

    setup_logging(Path(args.data_dir))

    logger = logging.getLogger(__name__)

    import uvicorn

    from backend.app.main import app  # noqa: E402

    restarts: list[float] = []
    backoff = 1

    while True:
        try:
            uvicorn.run(app, host="127.0.0.1", port=args.port)
            break  # Clean exit (e.g. graceful shutdown from Electron)
        except SystemExit:
            break  # Intentional exit — don't restart
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
