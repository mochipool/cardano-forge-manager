#!/usr/bin/env python3
"""
Test script to verify the startup status endpoint works correctly.
This can be used to test the endpoint locally before deployment.
"""

import json
import sys
import time
import urllib.request
import urllib.error


def test_startup_endpoint(host="localhost", port=8000, timeout=30):
    """Test the startup status endpoint."""
    url = f"http://{host}:{port}/startup-status"

    print(f"Testing startup status endpoint: {url}")
    print("=" * 50)

    start_time = time.time()

    while time.time() - start_time < timeout:
        try:
            req = urllib.request.Request(url)
            with urllib.request.urlopen(req, timeout=5) as response:
                status_code = response.getcode()
                content_type = response.headers.get("Content-Type", "")
                body = response.read().decode("utf-8")

                print(f"✓ HTTP {status_code}")
                print(f"✓ Content-Type: {content_type}")

                if content_type.startswith("application/json"):
                    try:
                        data = json.loads(body)
                        print(f"✓ Response: {json.dumps(data, indent=2)}")

                        if data.get("status") == "ready":
                            print("✓ Credentials are ready!")
                            return True
                        else:
                            print(f"⏳ Credentials not ready: {data.get('message')}")
                    except json.JSONDecodeError:
                        print(f"⚠ Invalid JSON response: {body}")
                else:
                    print(f"⚠ Non-JSON response: {body}")

        except urllib.error.HTTPError as e:
            if e.code == 503:
                print(f"⏳ Service unavailable (expected during startup): {e}")
                try:
                    body = e.read().decode("utf-8")
                    if body:
                        data = json.loads(body)
                        print(f"   Response: {json.dumps(data, indent=2)}")
                except:
                    pass
            else:
                print(f"⚠ HTTP error {e.code}: {e}")

        except urllib.error.URLError as e:
            print(f"⚠ Connection error: {e}")

        except Exception as e:
            print(f"⚠ Unexpected error: {e}")

        print("Waiting 2 seconds before retry...")
        time.sleep(2)

    print(f"❌ Timeout after {timeout} seconds")
    return False


def test_other_endpoints(host="localhost", port=8000):
    """Test other endpoints."""
    endpoints = [("/health", "Health check"), ("/metrics", "Prometheus metrics")]

    print("\\nTesting other endpoints:")
    print("=" * 50)

    for path, description in endpoints:
        url = f"http://{host}:{port}{path}"
        try:
            req = urllib.request.Request(url)
            with urllib.request.urlopen(req, timeout=5) as response:
                status_code = response.getcode()
                content_type = response.headers.get("Content-Type", "")
                body = response.read().decode("utf-8")

                print(f"✓ {description}: HTTP {status_code} ({content_type})")
                if len(body) > 200:
                    print(f"   Body: {body[:200]}...")
                else:
                    print(f"   Body: {body}")

        except Exception as e:
            print(f"⚠ {description}: {e}")


if __name__ == "__main__":
    if len(sys.argv) > 1:
        host = sys.argv[1]
    else:
        host = "localhost"

    if len(sys.argv) > 2:
        port = int(sys.argv[2])
    else:
        port = 8000

    print(f"Testing forge manager startup endpoint at {host}:{port}")
    print("Usage: python3 test-startup-endpoint.py [host] [port]")
    print("")

    # Test startup endpoint
    ready = test_startup_endpoint(host, port)

    # Test other endpoints
    test_other_endpoints(host, port)

    if ready:
        print("\\n✅ All tests passed - startup endpoint is working correctly!")
        sys.exit(0)
    else:
        print("\\n❌ Startup endpoint test failed")
        sys.exit(1)
