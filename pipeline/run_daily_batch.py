"""Generate, ingest, validate, and transform simulated operational data."""

from __future__ import annotations

import argparse
import os
from datetime import date, timedelta
from pathlib import Path

import psycopg

from .db import initialize_database, load_daily_batch
from .generate_data import generate_daily_data, write_jsonl

DEFAULT_DATABASE_URL = "postgresql://chat_admin:chat_admin@localhost:5432/chat_dashboard"


def main() -> None:
    parser = argparse.ArgumentParser(description="Run the customer chat analytics daily or bulk batch.")

    # Allow for either single day or a date range
    parser.add_argument("--date", dest="source_date", type=date.fromisoformat,
                        help="Run for a single specific date (YYYY-MM-DD)")
    parser.add_argument("--start-date", type=date.fromisoformat, help="Start date for bulk generation")
    parser.add_argument("--end-date", type=date.fromisoformat, help="End date for bulk generation")

    # NEW HACK: Fast simulation
    parser.add_argument("--skip-backups", action="store_true",
                        help="Skip writing JSONL files to disk to maximize speed")
    parser.add_argument("--fast-sim-days", type=int,
                        help="HACK: Quickly simulate the last N days directly to DB, skipping file I/O backups")

    parser.add_argument("--chat-count", type=int, default=250)
    parser.add_argument("--seed", type=int, help="Base seed for reproducibility")
    parser.add_argument("--output-dir", type=Path, default=Path("data/generated"))
    parser.add_argument(
        "--database-url",
        default=os.environ.get("DATABASE_URL", DEFAULT_DATABASE_URL),
    )
    args = parser.parse_args()

    # Determine the list of dates to process
    dates_to_process = []

    if args.fast_sim_days:
        # Hack mode: Just go backwards N days from today
        end_date = date.today()
        start_date = end_date - timedelta(days=args.fast_sim_days - 1)
        for i in range(args.fast_sim_days):
            dates_to_process.append(start_date + timedelta(days=i))
    elif args.start_date and args.end_date:
        delta = args.end_date - args.start_date
        for i in range(delta.days + 1):
            dates_to_process.append(args.start_date + timedelta(days=i))
    elif args.source_date:
        dates_to_process.append(args.source_date)
    else:
        dates_to_process.append(date.today())

    total_events, total_surveys = 0, 0

    # OPEN ONE DATABASE CONNECTION FOR THE ENTIRE BULK RUN
    with psycopg.connect(args.database_url) as connection:
        initialize_database(connection)

        mode_text = "FAST SIMULATION HACK" if args.fast_sim_days else "Standard Generation"
        print(f"Starting pipeline ({mode_text}) for {len(dates_to_process)} days...")

        for index, current_date in enumerate(dates_to_process):
            daily_seed = args.seed + index if args.seed is not None else int(current_date.strftime("%Y%m%d"))

            # 1. Generate in memory
            events, surveys = generate_daily_data(current_date, args.chat_count, daily_seed)

            # 2. Save JSONL backups (SKIPPED in fast sim mode to save I/O time)
            if not args.fast_sim_days:
                events_path, surveys_path = write_jsonl(
                    current_date,
                    events,
                    surveys,
                    args.output_dir,
                )

            # 3. Load to DB immediately
            load_daily_batch(connection, current_date, events, surveys)

            # Commit the transaction daily to prevent database memory overload on massive runs
            connection.commit()

            # Track totals
            total_events += len(events)
            total_surveys += len(surveys)

            print(
                f"[{index + 1}/{len(dates_to_process)}] Processed {current_date.isoformat()} - Loaded {len(events)} events.")

    print("\n--- Pipeline Run Completed ---")
    print(f"Total Days Processed: {len(dates_to_process)}")
    print(f"Total Events Loaded: {total_events}")
    print(f"Total Surveys Loaded: {total_surveys}")
    if args.fast_sim_days:
        print("Note: Skipped JSONL backups due to --fast-sim-days flag.")
    print("Tableau reporting schema refreshed: reporting")


if __name__ == "__main__":
    main()