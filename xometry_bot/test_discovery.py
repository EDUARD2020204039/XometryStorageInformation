import json
import tempfile
import unittest
from pathlib import Path

try:
    from .discovery import stamp_discovered_jobs
except ImportError:
    from discovery import stamp_discovered_jobs


class DiscoveryTests(unittest.TestCase):
    def test_first_seen_is_immutable_and_last_seen_advances(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            registry = Path(tmp_dir) / "job_discovery.json"
            first_jobs = [{"id": "HJO-1-2", "offer_id": "123"}]
            new_count, _ = stamp_discovered_jobs(
                first_jobs, str(registry), "2026-08-04T10:00:00Z"
            )

            second_jobs = [{"id": "HJO-1-2", "offer_id": "123"}]
            second_new_count, _ = stamp_discovered_jobs(
                second_jobs, str(registry), "2026-08-04T10:02:00Z"
            )

            self.assertEqual(new_count, 1)
            self.assertEqual(second_new_count, 0)
            self.assertEqual(second_jobs[0]["first_seen_at"], "2026-08-04T10:00:00Z")
            self.assertEqual(second_jobs[0]["last_seen_at"], "2026-08-04T10:02:00Z")
            self.assertEqual(second_jobs[0]["seen_count"], 2)
            saved = json.loads(registry.read_text(encoding="utf-8"))
            self.assertEqual(saved["jobs"]["offer:123"]["seen_count"], 2)

    def test_offer_id_is_stable_when_job_title_changes(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            registry = Path(tmp_dir) / "job_discovery.json"
            stamp_discovered_jobs(
                [{"id": "temporary-title", "offer_id": "456"}],
                str(registry),
                "2026-08-04T11:00:00Z",
            )
            jobs = [{"id": "J-200-300", "offer_id": "456"}]
            new_count, _ = stamp_discovered_jobs(
                jobs, str(registry), "2026-08-04T11:01:00Z"
            )

            self.assertEqual(new_count, 0)
            self.assertEqual(jobs[0]["first_seen_at"], "2026-08-04T11:00:00Z")

    def test_rfq_uses_persistent_external_identifier(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            registry = Path(tmp_dir) / "job_discovery.json"
            first = [{"id": "RFQ-23638388", "offer_id": "rfq:23638388"}]
            second = [{"id": "RFQ-23638388", "offer_id": "rfq:23638388"}]

            stamp_discovered_jobs(first, str(registry), "2026-08-05T09:00:00Z")
            new_count, _ = stamp_discovered_jobs(
                second, str(registry), "2026-08-05T09:01:00Z"
            )

            self.assertEqual(new_count, 0)
            self.assertEqual(second[0]["first_seen_at"], "2026-08-05T09:00:00Z")
            self.assertEqual(second[0]["last_seen_at"], "2026-08-05T09:01:00Z")
            self.assertEqual(second[0]["seen_count"], 2)


if __name__ == "__main__":
    unittest.main()
