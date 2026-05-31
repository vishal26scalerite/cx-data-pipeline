import unittest
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parent.parent
RAW_LAYER_SQL = PROJECT_ROOT / "sql" / "001_raw_layer.sql"


class RawLayerSqlTests(unittest.TestCase):
    def test_raw_chat_logs_constraints_accept_queue_events(self) -> None:
        sql = RAW_LAYER_SQL.read_text(encoding="utf-8")

        self.assertIn("'chat_entered_queue'", sql)
        self.assertIn("DROP CONSTRAINT IF EXISTS raw_chat_logs_event_type_ck", sql)
        self.assertIn("DROP CONSTRAINT IF EXISTS raw_chat_logs_agent_id_ck", sql)


if __name__ == "__main__":
    unittest.main()
