import unittest
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parent.parent
REPORTING_SQL = PROJECT_ROOT / "sql" / "003_reporting_views.sql"


class ReportingViewsSqlTests(unittest.TestCase):
    def test_reporting_views_expose_queue_wait_metrics(self) -> None:
        sql = REPORTING_SQL.read_text(encoding="utf-8")

        self.assertIn("DROP VIEW IF EXISTS reporting.v_tableau_chat_detail", sql)
        self.assertIn("fact.entered_queue_at", sql)
        self.assertIn("fact.queue_wait_seconds", sql)
        self.assertIn("queue_wait_minutes", sql)
        self.assertIn("avg_queue_wait_minutes", sql)


if __name__ == "__main__":
    unittest.main()
