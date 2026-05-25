import json
import tempfile
import unittest
from datetime import date, datetime, timedelta
from pathlib import Path

from pipeline.generate_data import generate_daily_data, validate_generated_data, write_jsonl


class GenerateDailyDataTests(unittest.TestCase):
    def setUp(self) -> None:
        self.source_date = date(2026, 5, 25)

    def test_daily_generation_is_deterministic_and_has_one_survey_per_chat(self) -> None:
        first_events, first_surveys = generate_daily_data(self.source_date, chat_count=100, seed=42)
        second_events, second_surveys = generate_daily_data(self.source_date, chat_count=100, seed=42)

        self.assertEqual(first_events, second_events)
        self.assertEqual(first_surveys, second_surveys)
        self.assertEqual(len(first_surveys), 100)
        self.assertEqual(len({row["chat_id"] for row in first_surveys}), 100)

    def test_inactivity_system_closure_occurs_exactly_one_hour_after_push(self) -> None:
        events, surveys = generate_daily_data(self.source_date, chat_count=300, seed=81)
        by_chat: dict[str, list[dict[str, object]]] = {}
        for event in events:
            by_chat.setdefault(str(event["chat_id"]), []).append(event)

        system_closed_chats = 0
        for chat_events in by_chat.values():
            pushed = next(
                (row for row in chat_events if row["event_type"] == "chat_pushed_to_queue_due_inactivity"),
                None,
            )
            closed = next(
                (row for row in chat_events if row["event_type"] == "system_closed_chat_after_inactivity"),
                None,
            )
            if closed:
                system_closed_chats += 1
                self.assertIsNotNone(pushed)
                self.assertEqual(
                    datetime.fromisoformat(str(closed["event_timestamp"]))
                    - datetime.fromisoformat(str(pushed["event_timestamp"])),
                    timedelta(hours=1),
                )

        self.assertGreater(system_closed_chats, 0)
        validate_generated_data(events, surveys)

    def test_write_jsonl_creates_daily_source_delivery(self) -> None:
        events, surveys = generate_daily_data(self.source_date, chat_count=3, seed=4)
        with tempfile.TemporaryDirectory() as temp_directory:
            events_path, surveys_path = write_jsonl(
                self.source_date,
                events,
                surveys,
                Path(temp_directory),
            )
            with events_path.open(encoding="utf-8") as event_file:
                stored_events = [json.loads(line) for line in event_file]
            with surveys_path.open(encoding="utf-8") as survey_file:
                stored_surveys = [json.loads(line) for line in survey_file]

        self.assertEqual(stored_events, events)
        self.assertEqual(stored_surveys, surveys)


if __name__ == "__main__":
    unittest.main()

