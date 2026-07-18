import unittest

from xometry_bot.order_sync import select_order_links, should_persist_seen_state


class OrderSyncPolicyTests(unittest.TestCase):
    def test_recent_pages_are_refreshed_even_when_seen(self):
        selected, new = select_order_links(
            ["https://partner.xometry.eu/orders/1", "https://partner.xometry.eu/orders/2"],
            {"1"},
            page_number=1,
            process_only_new=True,
            refresh_recent_pages=2,
        )
        self.assertEqual(len(selected), 2)
        self.assertEqual(new, ["https://partner.xometry.eu/orders/2"])

    def test_old_pages_only_process_new_orders(self):
        selected, _ = select_order_links(
            ["https://partner.xometry.eu/orders/1", "https://partner.xometry.eu/orders/2"],
            {"1"},
            page_number=3,
            process_only_new=True,
            refresh_recent_pages=2,
        )
        self.assertEqual(selected, ["https://partner.xometry.eu/orders/2"])

    def test_failed_backend_does_not_advance_seen_state(self):
        self.assertFalse(should_persist_seen_state(records_sent=3, backend_accepted=False))
        self.assertTrue(should_persist_seen_state(records_sent=3, backend_accepted=True))
        self.assertTrue(should_persist_seen_state(records_sent=0, backend_accepted=False))


if __name__ == "__main__":
    unittest.main()
