"""PostgreSQL DDL execution and raw-to-mart batch loading."""

from __future__ import annotations

from datetime import date
from pathlib import Path
from typing import Any

import psycopg


PROJECT_ROOT = Path(__file__).resolve().parent.parent
SQL_FILES = [
    PROJECT_ROOT / "sql" / "001_raw_layer.sql",
    PROJECT_ROOT / "sql" / "002_star_schema.sql",
    PROJECT_ROOT / "sql" / "003_reporting_views.sql",
]


def initialize_database(connection: psycopg.Connection[Any]) -> None:
    """Apply idempotent database objects before each load."""
    with connection.cursor() as cursor:
        for sql_file in SQL_FILES:
            cursor.execute(sql_file.read_text(encoding="utf-8"))
    connection.commit()


def load_daily_batch(
    connection: psycopg.Connection[Any],
    source_date: date,
    events: list[dict[str, Any]],
    surveys: list[dict[str, Any]],
) -> None:
    """Persist immutable source events (Idempotent execution)."""
    event_rows = [
        (
            event["event_id"], event["chat_id"], event["agent_id"],
            event["event_type"], event["event_timestamp"], event["ingestion_date"],
        ) for event in events
    ]
    survey_rows = [
        (
            survey["survey_id"], survey["chat_id"], survey["survey_skipped"], survey["customer_input"],
        ) for survey in surveys
    ]

    with connection.transaction():
        with connection.cursor() as cursor:
            # 1. Idempotent Override
            cursor.execute(
                "DELETE FROM raw.survey WHERE chat_id IN (SELECT chat_id FROM raw.raw_chat_logs WHERE DATE(event_timestamp) = %s)",
                (source_date,)
            )
            cursor.execute("DELETE FROM raw.raw_chat_logs WHERE DATE(event_timestamp) = %s", (source_date,))

            # 2. Insertion
            cursor.executemany(
                """INSERT INTO raw.raw_chat_logs (event_id, chat_id, agent_id, event_type, event_timestamp, ingestion_date)
                   VALUES (%s, %s, %s, %s, %s, %s) ON CONFLICT (event_id) DO NOTHING""",
                event_rows,
            )
            cursor.executemany(
                """INSERT INTO raw.survey (survey_id, chat_id, survey_skipped, customer_input)
                   VALUES (%s, %s, %s, %s) ON CONFLICT (survey_id) DO NOTHING""",
                survey_rows,
            )

            # Log the successful daily ingestion
            cursor.execute(
                "INSERT INTO raw.batch_run_log (source_date, source_chat_count, source_event_count) VALUES (%s, %s, %s)",
                (source_date, len(surveys), len(events)),
            )

def refresh_analytics_models(connection: psycopg.Connection[Any]) -> None:
    """Run heavy aggregations and data modeling ONCE after all data is loaded."""
    with connection.transaction():
        with connection.cursor() as cursor:
            cursor.execute("CALL raw.validate_source_data()")
            cursor.execute("CALL mart.refresh_star_schema()")