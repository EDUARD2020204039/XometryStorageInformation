import unittest
from unittest.mock import patch

from XometryAnaliza.app import watchdog


class WatchdogContextTests(unittest.TestCase):
    def test_recent_failed_event_is_enriched_from_job_state(self):
        event = {
            "ts": 950,
            "type": "sheet.done",
            "message": "Sheet agent finished HJO-38963-105: failed",
            "job_id": "HJO-38963-105",
            "offer_id": "47969706",
        }
        state = {
            "sheet_metal_laser": {
                "status": "failed",
                "error": "Nu am reusit sa deschid fisierul sursa in TecZone.",
                "failure_type": "open_source_failed",
                "failure_action": "Verifica STEP-ul si starea TecZone.",
                "geo_ready_count": 0,
                "geo_requested_count": 1,
                "diagnostic": {
                    "category": "teczone_unfold",
                    "summary": "TecZone nu a deschis fisierul sursa.",
                },
            }
        }

        with (
            patch.object(watchdog.time, "time", return_value=1000),
            patch.object(watchdog.settings, "WATCHDOG_RECENT_ERROR_SECONDS", 300),
            patch.object(watchdog, "read_events", return_value=[event]),
            patch.object(watchdog, "load_job_state", return_value=state),
        ):
            result = watchdog._check_recent_flow_errors()

        example = result["details"]["examples"][0]
        self.assertEqual(example["failure_type"], "open_source_failed")
        self.assertEqual(example["diagnostic_category"], "teczone_unfold")
        self.assertIn("TecZone", example["error"])
        self.assertEqual(example["geo_ready_count"], 0)

    def test_event_payload_wins_without_state_lookup(self):
        event = {
            "ts": 950,
            "type": "sheet.done",
            "message": "Sheet agent finished HJO-1: failed",
            "job_id": "HJO-1",
            "status": "failed",
            "error": "explicit failure",
            "failure_type": "open_source_failed",
        }
        with (
            patch.object(watchdog.time, "time", return_value=1000),
            patch.object(watchdog.settings, "WATCHDOG_RECENT_ERROR_SECONDS", 300),
            patch.object(watchdog, "read_events", return_value=[event]),
            patch.object(watchdog, "load_job_state") as load_state,
        ):
            result = watchdog._check_recent_flow_errors()

        load_state.assert_not_called()
        self.assertEqual(result["details"]["examples"][0]["error"], "explicit failure")

    def test_multiple_events_for_same_job_are_one_incident(self):
        events = [
            {"ts": 940, "type": "ofertare.log", "message": "ConnectionResetError 10054", "job_id": "HJO-1"},
            {"ts": 950, "type": "sheet.blocked", "message": "HJO-1 failed", "job_id": "HJO-1"},
            {"ts": 960, "type": "sheet.done", "message": "HJO-1 failed", "job_id": "HJO-1"},
        ]
        state = {
            "sheet_metal_laser": {
                "status": "failed",
                "error": "ConnectionResetError 10054",
                "failure_type": "agent_error",
            }
        }
        with (
            patch.object(watchdog.time, "time", return_value=1000),
            patch.object(watchdog.settings, "WATCHDOG_RECENT_ERROR_SECONDS", 300),
            patch.object(watchdog, "read_events", return_value=events),
            patch.object(watchdog, "load_job_state", return_value=state),
        ):
            result = watchdog._check_recent_flow_errors()

        self.assertEqual(result["details"]["raw_event_count"], 3)
        self.assertEqual(result["details"]["hit_count"], 1)
        self.assertEqual(len(result["details"]["examples"]), 1)
        self.assertEqual(result["details"]["examples"][0]["related_event_count"], 3)


if __name__ == "__main__":
    unittest.main()
