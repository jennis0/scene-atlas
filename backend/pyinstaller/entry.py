"""PyInstaller entry point for Scene Atlas backend sidecar.

Sets environment variables BEFORE importing any backend.app modules,
because importing config.py immediately constructs Settings() and
computes all derived paths from data_dir.
"""

import argparse
import os


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

    # Set up logging before importing the app (which also calls setup_logging,
    # but the guard in setup_logging prevents duplicate handlers).
    from pathlib import Path

    from backend.app.logging_config import setup_logging

    setup_logging(Path(args.data_dir))

    # Import app object directly (not as a string) — uvicorn.run("module:app")
    # uses importlib at runtime which doesn't work in a frozen PyInstaller binary.
    # A direct import also lets PyInstaller detect and bundle the backend package.
    import uvicorn

    from backend.app.main import app  # noqa: E402

    uvicorn.run(app, host="127.0.0.1", port=args.port)


if __name__ == "__main__":
    main()
