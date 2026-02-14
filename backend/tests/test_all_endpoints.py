"""Manual test script for all API endpoints."""

import sys
from pathlib import Path
import time
import subprocess
import requests

# Start the server in background
print("Starting server...")
server_process = subprocess.Popen(
    [sys.executable, "-m", "backend.app.main"],
    stdout=subprocess.PIPE,
    stderr=subprocess.PIPE,
    cwd=Path(__file__).parent,
)

# Wait for server to start
time.sleep(3)

BASE_URL = "http://localhost:8000"

def test_endpoint(name, method, url, expected_keys=None, params=None):
    """Test an endpoint."""
    try:
        if method == "GET":
            response = requests.get(url, params=params, timeout=5)
        else:
            response = requests.post(url, json=params, timeout=5)

        if response.status_code == 200:
            data = response.json()
            if expected_keys:
                missing = [k for k in expected_keys if k not in data]
                if missing:
                    print(f"  [WARN] {name}: Missing keys: {missing}")
                else:
                    print(f"  [OK] {name}")
            else:
                print(f"  [OK] {name}")
            return data
        else:
            print(f"  [FAIL] {name}: Status {response.status_code}")
            return None
    except Exception as e:
        print(f"  [ERROR] {name}: {e}")
        return None

try:
    print("\n=== Testing API Endpoints ===\n")

    # Health endpoints
    print("Health & Root:")
    test_endpoint("Root", "GET", f"{BASE_URL}/", ["app", "version", "status"])
    test_endpoint("Health", "GET", f"{BASE_URL}/health", ["status"])

    # Image endpoints
    print("\nImage Endpoints:")
    images = test_endpoint("List images", "GET", f"{BASE_URL}/api/v1/images/")
    if images and len(images) > 0:
        image_id = images[0]["id"]
        test_endpoint("Get image", "GET", f"{BASE_URL}/api/v1/images/{image_id}")
        test_endpoint("Get variants", "GET", f"{BASE_URL}/api/v1/images/{image_id}/variants")
    else:
        print("  [SKIP] No images available for testing")

    # Tag endpoints
    print("\nTag Endpoints:")
    categories = test_endpoint("List tag categories", "GET", f"{BASE_URL}/api/v1/tags/categories")
    if categories:
        test_endpoint("Get tag category", "GET", f"{BASE_URL}/api/v1/tags/categories/grid")
        test_endpoint("Get tag values", "GET", f"{BASE_URL}/api/v1/tags/values/grid")
    test_endpoint("Tag statistics", "GET", f"{BASE_URL}/api/v1/tags/stats")

    # Search endpoints
    print("\nSearch Endpoints:")
    test_endpoint("Search (no params)", "GET", f"{BASE_URL}/api/v1/search/", ["total", "images"])
    test_endpoint("Search by text", "GET", f"{BASE_URL}/api/v1/search/", params={"text": "mine"})
    test_endpoint("Search by author", "GET", f"{BASE_URL}/api/v1/search/", params={"author": "czepeku"})
    test_endpoint("Search by tags", "GET", f"{BASE_URL}/api/v1/search/", params={"tags": ["state:abandoned"]})

    # Semantic search
    print("\nSemantic Search:")
    result = test_endpoint("Semantic search", "GET", f"{BASE_URL}/api/v1/search/semantic", params={"query": "abandoned mine", "limit": 10})
    if result:
        if "error" in result and result["error"]:
            print(f"    [ERROR] Semantic search has error: {result['error']}")
        elif "results" in result:
            print(f"    Found {len(result.get('results', []))} results")
            if len(result.get('results', [])) > 0:
                print(f"    Top result score: {result['results'][0].get('score', 'N/A')}")

    print("\n=== Test Complete ===")

finally:
    # Stop the server
    print("\nStopping server...")
    server_process.terminate()
    server_process.wait(timeout=5)
    print("Server stopped.")
