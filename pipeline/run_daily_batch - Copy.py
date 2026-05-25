"""Generate, ingest, validate, and transform one simulated operational day."""

from __future__ import annotations

import argparse
import os
from datetime import date
from pathlib import Path

import psycopg

from .db import initialize_database, load_daily_batch
from .generate_data import generate_daily_data, write_jsonl


DEFAULT_DATABASE_URL = "postgresql://chat_admin:chat_admin@localhost:5432/chat_dashboard"


def main() -> None:
    parser = argparse.ArgumentParser(description="Run the customer chat analytics daily batch.")
    parser.add_argument("--date", dest="source_date", type=date.fromisoformat, default=date.today())
    parser.add_argument("--chat-count", type=int, default=250)
    parser.add_argument("--seed", type=int)
    parser.add_argument("--output-dir", type=Path, default=Path("data/generated"))
    parser.add_argument(
        "--database-url",
        default=os.environ.get("DATABASE_URL", DEFAULT_DATABASE_URL),
    )
    args = parser.parse_args()

    events, surveys = generate_daily_data(args.source_date, args.chat_count, args.seed)
    events_path, surveys_path = write_jsonl(
        args.source_date,
        events,
        surveys,
        args.output_dir,
    )

    with psycopg.connect(args.database_url) as connection:
        initialize_database(connection)
        load_daily_batch(connection, args.source_date, events, surveys)

    print(f"Batch completed for {args.source_date.isoformat()}.")
    print(f"Loaded {len(events)} events and {len(surveys)} surveys.")
    print(f"Source events file: {events_path}")
    print(f"Source surveys file: {surveys_path}")
    print("Tableau reporting schema refreshed: reporting")


if __name__ == "__main__":
    main()

