"""Test that the server starts and responds."""

import sys
import time
import subprocess
from pathlib import Path
import requests

# Start the server in a subprocess
print("Starting server...")
server_process = subprocess.Popen(
    [sys.executable, "-m", "backend.app.main"],
    stdout=subprocess.PIPE,
    stderr=subprocess.PIPE,
    cwd=Path(__file__).parent,
)

# Wait for server to start
time.sleep(3)

try:
    # Test health endpoint
    print("Testing health endpoint...")
    response = requests.get("http://localhost:8000/health", timeout=5)
    print(f"[OK] Health check: {response.json()}")

    # Test root endpoint
    print("Testing root endpoint...")
    response = requests.get("http://localhost:8000/", timeout=5)
    print(f"[OK] Root: {response.json()}")

    # Test tag categories endpoint
    print("Testing tag categories endpoint...")
    response = requests.get("http://localhost:8000/api/v1/tags/categories", timeout=5)
    categories = response.json()
    print(f"[OK] Found {len(categories)} tag categories")

    print("\n=== Server is working correctly! ===")
    print("\nAPI Documentation: http://localhost:8000/docs")

except Exception as e:
    print(f"[ERROR] {e}")
    import traceback

    traceback.print_exc()
finally:
    # Stop the server
    print("\nStopping server...")
    server_process.terminate()
    server_process.wait(timeout=5)
    print("Server stopped.")
