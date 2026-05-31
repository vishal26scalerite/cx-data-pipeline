import re
import unittest
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parent.parent
STAR_SCHEMA_SQL = PROJECT_ROOT / "sql" / "002_star_schema.sql"


class StarSchemaSqlTests(unittest.TestCase):
    def test_refresh_star_schema_rolls_up_queue_wait_metrics(self) -> None:
        sql = STAR_SCHEMA_SQL.read_text(encoding="utf-8")

        self.assertIn("entered_queue_at TIMESTAMP", sql)
        self.assertIn("queue_wait_seconds INTEGER", sql)
        self.assertIn("ADD COLUMN IF NOT EXISTS entered_queue_at", sql)
        self.assertIn("ADD COLUMN IF NOT EXISTS queue_wait_seconds", sql)
        self.assertIn("event_type = 'chat_entered_queue'", sql)
        self.assertIn("rollup.assigned_at - rollup.entered_queue_at", sql)
        self.assertIn("entered_queue_at = EXCLUDED.entered_queue_at", sql)
        self.assertIn("queue_wait_seconds = EXCLUDED.queue_wait_seconds", sql)

    def test_refresh_star_schema_deletes_facts_missing_from_current_source(self) -> None:
        sql = STAR_SCHEMA_SQL.read_text(encoding="utf-8")

        self.assertRegex(
            sql,
            re.compile(
                r"deleted_stale_facts AS \(\s+"
                r"DELETE FROM mart\.fact_chat_resolution fact\s+"
                r"WHERE NOT EXISTS \(\s+"
                r"SELECT 1\s+"
                r"FROM fact_source source\s+"
                r"WHERE source\.chat_id = fact\.chat_id\s+"
                r"\)\s+"
                r"RETURNING fact\.chat_id\s+"
                r"\)\s+"
                r"INSERT INTO mart\.fact_chat_resolution",
                re.MULTILINE,
            ),
        )


if __name__ == "__main__":
    unittest.main()
