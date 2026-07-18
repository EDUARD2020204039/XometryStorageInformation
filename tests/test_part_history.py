import unittest

from xometry.part_history import match_part, normalize_part_name, part_tokens


class PartHistoryTests(unittest.TestCase):
    def test_conversion_suffix_is_ignored(self):
        name = "2D_ST1A85385_02_--.02_AD_MCCBB0049_converted_20260109152855.pdf"
        self.assertEqual(normalize_part_name(name), "2d st1a85385 02 .02 ad mccbb0049")
        self.assertEqual(part_tokens(name), ["st1a85385", "mccbb0049"])

    def test_truncated_name_matches_by_drawing_code_and_geometry(self):
        verdict = match_part(
            query_part_id="844207",
            query_name="2D_ST1A85385_02_...260109152855.pdf",
            candidate_part_id="991122",
            candidate_name="2D_ST1A85385_02_--.02_AD_MCCBB0049_converted_20260109152855.pdf",
            query_material="Aluminium EN AW-6082 T6",
            candidate_material="Aluminium EN AW-6082 T6",
            query_dimensions=(45, 25, 12),
            candidate_dimensions=(25, 45, 12),
        )
        self.assertGreaterEqual(verdict["score"], 75)
        self.assertIn("dimensiuni identice", verdict["reasons"])

    def test_unrelated_part_is_rejected(self):
        verdict = match_part(
            query_part_id="844207",
            query_name="ST1A85385.pdf",
            candidate_part_id="123",
            candidate_name="OTHER12345.pdf",
        )
        self.assertEqual(verdict["score"], 0)


if __name__ == "__main__":
    unittest.main()
