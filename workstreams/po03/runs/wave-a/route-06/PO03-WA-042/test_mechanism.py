import tempfile
import unittest
from pathlib import Path
from mechanism import deliver, open_db, replay, stage_result


class OutboxTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.db = open_db(Path(self.tmp.name) / "test.db")

    def tearDown(self):
        self.db.close()
        self.tmp.cleanup()

    def test_lost_callback_is_replayed(self):
        event = stage_result(self.db, "task-1", {"state": "RESULT_STAGED"})
        self.assertEqual(0, self.db.execute("SELECT count(*) FROM callbacks").fetchone()[0])
        self.assertEqual(["DELIVERED"], replay(self.db))
        self.assertEqual(1, self.db.execute("SELECT count(*) FROM callbacks WHERE event_id=?", (event,)).fetchone()[0])

    def test_crash_after_effect_replays_without_duplicate_effect(self):
        event = stage_result(self.db, "task-2", {"state": "RESULT_STAGED"})
        self.assertEqual("CRASHED_AFTER_IDEMPOTENT_EFFECT", deliver(self.db, event, True))
        self.assertEqual(["DUPLICATE_ACKNOWLEDGED"], replay(self.db))
        self.assertEqual(1, self.db.execute("SELECT count(*) FROM callbacks WHERE event_id=?", (event,)).fetchone()[0])

    def test_business_result_and_outbox_are_atomic(self):
        with self.assertRaises(Exception):
            with self.db:
                self.db.execute("INSERT INTO results VALUES ('task-3', '{}')")
                self.db.execute("INSERT INTO outbox(event_id, task_id, payload) VALUES (NULL, NULL, NULL)")
        self.assertEqual(0, self.db.execute("SELECT count(*) FROM results WHERE task_id='task-3'").fetchone()[0])


if __name__ == "__main__":
    unittest.main()
