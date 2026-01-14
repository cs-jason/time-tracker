import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

from tt_db import Config, init_database
from tt_models import Activity
from tt_sessions import SessionManager
from tt_db import get_db_connection


class TestSessionManager(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.TemporaryDirectory()
        self.db_path = Path(self.tmpdir.name) / "test.db"
        init_database(self.db_path)
        with get_db_connection(self.db_path) as conn:
            conn.execute("INSERT INTO projects (name) VALUES ('Test')")
            conn.execute(
                "INSERT INTO rules (project_id, rule_type, rule_value, rule_group, enabled) "
                "VALUES (1, 'app_contains', 'Code', 0, 1)"
            )

    def tearDown(self):
        self.tmpdir.cleanup()

    def test_idle_grace_not_counted(self):
        config = Config(
            poll_interval=2,
            idle_threshold=1,
            idle_grace_period=5,
            session_grace_period=5,
            min_session_duration=0,
        )
        manager = SessionManager(config, self.db_path)

        t0 = datetime.now(timezone.utc)
        t1 = t0 + timedelta(seconds=2)
        t2 = t1 + timedelta(seconds=2)
        t3 = t2 + timedelta(seconds=10)

        active = Activity(t0, "Code", None, None, None, None, False)
        manager.process_activity(active)
        active2 = Activity(t1, "Code", None, None, None, None, False)
        manager.process_activity(active2)

        idle = Activity(t2, "Code", None, None, None, None, True)
        manager.process_activity(idle)

        idle_late = Activity(t3, "Code", None, None, None, None, True)
        manager.process_activity(idle_late)

        with get_db_connection(self.db_path) as conn:
            row = conn.execute("SELECT duration FROM sessions").fetchone()
        self.assertIsNotNone(row)
        self.assertEqual(row["duration"], 2)


if __name__ == "__main__":
    unittest.main()
