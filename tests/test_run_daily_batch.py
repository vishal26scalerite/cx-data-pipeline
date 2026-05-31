import importlib
import sys
import types
import unittest
from datetime import date
from unittest.mock import Mock, patch


if "psycopg" not in sys.modules:
    sys.modules["psycopg"] = types.SimpleNamespace(connect=Mock())

run_daily_batch = importlib.import_module("pipeline.run_daily_batch")


class FakeConnection:
    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, traceback):
        return False

    def commit(self):
        pass


class RunDailyBatchTests(unittest.TestCase):
    def test_refreshes_analytics_models_once_after_all_dates_are_loaded(self) -> None:
        connection = FakeConnection()
        events = [{"event_id": "event_1"}]
        surveys = [{"survey_id": "survey_1"}]
        call_order: list[str] = []

        with (
            patch.object(
                sys,
                "argv",
                [
                    "run_daily_batch",
                    "--start-date",
                    "2026-05-01",
                    "--end-date",
                    "2026-05-02",
                    "--chat-count",
                    "1",
                    "--seed",
                    "20260501",
                ],
            ),
            patch.object(run_daily_batch.psycopg, "connect", return_value=connection),
            patch.object(run_daily_batch, "initialize_database"),
            patch.object(run_daily_batch, "generate_daily_data", return_value=(events, surveys)),
            patch.object(run_daily_batch, "write_jsonl", return_value=("events.jsonl", "surveys.jsonl")),
            patch.object(
                run_daily_batch,
                "load_daily_batch",
                side_effect=lambda *_args: call_order.append("load"),
            ) as load_daily_batch,
            patch.object(
                run_daily_batch,
                "refresh_analytics_models",
                side_effect=lambda *_args: call_order.append("refresh"),
            ) as refresh_analytics_models,
            patch("builtins.print"),
        ):
            run_daily_batch.main()

        self.assertEqual(
            [
                call.args[1]
                for call in load_daily_batch.call_args_list
            ],
            [date(2026, 5, 1), date(2026, 5, 2)],
        )
        refresh_analytics_models.assert_called_once_with(connection)
        self.assertEqual(call_order, ["load", "load", "refresh"])

    def test_skip_backups_loads_without_writing_jsonl_files(self) -> None:
        connection = FakeConnection()
        events = [{"event_id": "event_1"}]
        surveys = [{"survey_id": "survey_1"}]

        with (
            patch.object(
                sys,
                "argv",
                [
                    "run_daily_batch",
                    "--date",
                    "2026-05-01",
                    "--chat-count",
                    "1",
                    "--seed",
                    "20260501",
                    "--skip-backups",
                ],
            ),
            patch.object(run_daily_batch.psycopg, "connect", return_value=connection),
            patch.object(run_daily_batch, "initialize_database"),
            patch.object(run_daily_batch, "generate_daily_data", return_value=(events, surveys)),
            patch.object(run_daily_batch, "write_jsonl") as write_jsonl,
            patch.object(run_daily_batch, "load_daily_batch") as load_daily_batch,
            patch.object(run_daily_batch, "refresh_analytics_models"),
            patch("builtins.print"),
        ):
            run_daily_batch.main()

        write_jsonl.assert_not_called()
        load_daily_batch.assert_called_once_with(connection, date(2026, 5, 1), events, surveys)


if __name__ == "__main__":
    unittest.main()
