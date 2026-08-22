import unittest
from mechanism import acquire, fenced_write, new_store


class FenceTests(unittest.TestCase):
    def test_tokens_are_monotonic(self):
        db = new_store()
        self.assertEqual(1, acquire(db, "worker-a"))
        self.assertEqual(2, acquire(db, "worker-b"))

    def test_stale_worker_cannot_overwrite_transfer(self):
        db = new_store()
        old = acquire(db, "worker-a")
        current = acquire(db, "worker-b")
        self.assertTrue(fenced_write(db, current, "current"))
        self.assertFalse(fenced_write(db, old, "stale"))
        self.assertEqual("current", db.execute("SELECT value FROM custody").fetchone()[0])

    def test_current_owner_can_write_repeatedly(self):
        db = new_store()
        token = acquire(db, "worker-a")
        self.assertTrue(fenced_write(db, token, "one"))
        self.assertTrue(fenced_write(db, token, "two"))


if __name__ == "__main__":
    unittest.main()
