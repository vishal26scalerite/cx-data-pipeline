import os
import unittest
from datetime import date

try:
    import psycopg
    from psycopg import OperationalError
except ModuleNotFoundError:
    psycopg = None
    OperationalError = Exception


DEFAULT_DATABASE_URL = "postgresql://chat_admin:chat_admin@localhost:5432/chat_dashboard"


class RollbackTestData(Exception):
    pass


@unittest.skipIf(psycopg is None, "psycopg is not installed")
class PostgresIntegrationTests(unittest.TestCase):
    def connect(self):
        database_url = os.environ.get("DATABASE_URL", DEFAULT_DATABASE_URL)
        try:
            return psycopg.connect(database_url, connect_timeout=3)
        except OperationalError as exc:
            self.skipTest(f"PostgreSQL is not reachable at {database_url}: {exc}")

    def test_generate_load_validate_refresh_and_query_reporting_views(self) -> None:
        from pipeline.db import initialize_database, load_daily_batch, refresh_analytics_models
        from pipeline.generate_data import generate_daily_data

        source_date = date(2099, 1, 1)
        chat_count = 25
        events, surveys = generate_daily_data(source_date, chat_count=chat_count, seed=20990101)
        chat_id_prefix = "chat_20990101_"

        connection = self.connect()
        self.addCleanup(connection.close)
        initialize_database(connection)

        try:
            with connection.transaction():
                load_daily_batch(connection, source_date, events, surveys)
                refresh_analytics_models(connection)

                with connection.cursor() as cursor:
                    cursor.execute(
                        "SELECT COUNT(*) FROM raw.raw_chat_logs WHERE ingestion_date = %s",
                        (source_date,),
                    )
                    raw_event_count = cursor.fetchone()[0]

                    cursor.execute(
                        """
                        SELECT
                            COUNT(*),
                            COUNT(*) FILTER (WHERE entered_queue_at IS NOT NULL),
                            COUNT(*) FILTER (WHERE assigned_at IS NOT NULL),
                            COUNT(queue_wait_seconds),
                            MIN(queue_wait_seconds)
                        FROM mart.fact_chat_resolution
                        WHERE chat_id LIKE %s
                        """,
                        (f"{chat_id_prefix}%",),
                    )
                    (
                        fact_count,
                        fact_queue_entry_count,
                        fact_assigned_count,
                        fact_queue_wait_count,
                        min_queue_wait_seconds,
                    ) = cursor.fetchone()

                    cursor.execute(
                        """
                        SELECT
                            COUNT(*),
                            COUNT(*) FILTER (WHERE entered_queue_at IS NOT NULL),
                            COUNT(queue_wait_seconds)
                        FROM reporting.v_tableau_chat_detail
                        WHERE chat_id LIKE %s
                        """,
                        (f"{chat_id_prefix}%",),
                    )
                    detail_count, detail_queue_entry_count, detail_queue_wait_count = (
                        cursor.fetchone()
                    )

                    cursor.execute(
                        """
                        SELECT COUNT(*), COUNT(avg_queue_wait_minutes)
                        FROM reporting.v_chat_kpi_summary_daily
                        WHERE chat_date = %s
                        """,
                        (source_date,),
                    )
                    daily_kpi_rows, daily_queue_metric_rows = cursor.fetchone()

                    cursor.execute(
                        """
                        SELECT COUNT(*), COUNT(avg_queue_wait_minutes)
                        FROM reporting.v_agent_performance_daily
                        WHERE chat_date = %s
                        """,
                        (source_date,),
                    )
                    agent_performance_rows, agent_queue_metric_rows = cursor.fetchone()

                self.assertEqual(raw_event_count, len(events))
                self.assertEqual(fact_count, chat_count)
                self.assertEqual(fact_queue_entry_count, chat_count)
                self.assertEqual(fact_queue_wait_count, fact_assigned_count)
                self.assertIsNotNone(min_queue_wait_seconds)
                self.assertGreaterEqual(min_queue_wait_seconds, 0)
                self.assertEqual(detail_count, chat_count)
                self.assertEqual(detail_queue_entry_count, chat_count)
                self.assertEqual(detail_queue_wait_count, fact_queue_wait_count)
                self.assertGreater(daily_kpi_rows, 0)
                self.assertGreater(daily_queue_metric_rows, 0)
                self.assertGreater(agent_performance_rows, 0)
                self.assertGreater(agent_queue_metric_rows, 0)

                raise RollbackTestData
        except RollbackTestData:
            pass


if __name__ == "__main__":
    unittest.main()
