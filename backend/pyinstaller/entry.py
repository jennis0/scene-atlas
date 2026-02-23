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

    import uvicorn

    uvicorn.run("backend.app.main:app", host="127.0.0.1", port=args.port)


if __name__ == "__main__":
    main()
