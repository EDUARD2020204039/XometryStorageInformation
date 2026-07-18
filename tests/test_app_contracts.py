import os
import sys
import tempfile
import unittest
from collections import Counter
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
APP_ROOT = REPO_ROOT / "xometry-app"
TEST_DATA = tempfile.TemporaryDirectory()

os.environ["DATABASE_URL"] = f"sqlite:///{Path(TEST_DATA.name) / 'contracts.db'}"
os.environ["XSI_API_AUTH_REQUIRED"] = "false"
sys.path.insert(0, str(APP_ROOT))

from fastapi.testclient import TestClient  # noqa: E402
from app import app  # noqa: E402
from xometry.db import get_engine  # noqa: E402


class AppContractTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.client = TestClient(app)

    @classmethod
    def tearDownClass(cls):
        cls.client.close()
        get_engine().dispose()
        TEST_DATA.cleanup()

    def test_no_duplicate_http_method_and_path(self):
        route_keys = []
        for route in app.routes:
            for method in getattr(route, "methods", set()):
                route_keys.append((method, route.path))

        duplicates = [key for key, count in Counter(route_keys).items() if count > 1]
        self.assertEqual(duplicates, [])

    def test_health_and_readiness_contracts(self):
        health = self.client.get("/api/health")
        self.assertEqual(health.status_code, 200)
        self.assertEqual(health.json()["status"], "healthy")

        ready = self.client.get("/api/ready")
        self.assertEqual(ready.status_code, 200)
        self.assertEqual(ready.json()["status"], "ready")

    def test_versioned_and_legacy_history_routes_are_published(self):
        paths = {route.path for route in app.routes}
        self.assertIn("/api/v1/parts/history", paths)
        self.assertIn("/api/parts/history", paths)
        self.assertIn("/api/v1/orders/summary", paths)

        summary = self.client.get("/api/v1/orders/summary")
        self.assertEqual(summary.status_code, 200)
        self.assertEqual(summary.json()["total_orders"], 0)
        self.assertEqual(summary.json()["total_rows"], 0)


if __name__ == "__main__":
    unittest.main()
