"""Generate deterministic daily chat events and survey source files."""

from __future__ import annotations

import argparse
import json
import random
from collections import defaultdict
from datetime import date, datetime, time, timedelta
from pathlib import Path
from typing import Any


EVENT_TYPES = {
    "chat_started",
    "agent_assignment",
    "agent_responded",
    "customer_responded",
    "chat_closed_by_agent",
    "customer_closed_chat",
    "chat_pushed_to_queue_due_inactivity",
    "system_closed_chat_after_inactivity",
}
NULL_AGENT_EVENTS = {
    "chat_started",
    "customer_responded",
    "customer_closed_chat",
    "system_closed_chat_after_inactivity",
}
REQUIRED_AGENT_EVENTS = {
    "agent_assignment",
    "agent_responded",
    "chat_closed_by_agent",
    "chat_pushed_to_queue_due_inactivity",
}
CLOSURE_EVENTS = {
    "chat_closed_by_agent",
    "customer_closed_chat",
    "system_closed_chat_after_inactivity",
}
AGENT_IDS = list(range(1001, 1013))


def _timestamp(value: str) -> datetime:
    return datetime.fromisoformat(value)


def _new_event(
    chat_id: str,
    event_number: int,
    event_type: str,
    event_timestamp: datetime,
    agent_id: int | None,
    ingestion_date: date,
) -> dict[str, Any]:
    return {
        "event_id": f"{chat_id}_event_{event_number:02d}",
        "chat_id": chat_id,
        "agent_id": agent_id,
        "event_type": event_type,
        "event_timestamp": event_timestamp.isoformat(sep=" "),
        "ingestion_date": ingestion_date.isoformat(),
    }


def generate_daily_data(
    ingestion_date: date,
    chat_count: int = 250,
    seed: int | None = None,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Return generated raw events and surveys for one source-system day."""
    if chat_count < 1:
        raise ValueError("chat_count must be positive")

    effective_seed = seed if seed is not None else int(ingestion_date.strftime("%Y%m%d"))
    rng = random.Random(effective_seed)
    events: list[dict[str, Any]] = []
    surveys: list[dict[str, Any]] = []

    for chat_number in range(1, chat_count + 1):
        chat_id = f"chat_{ingestion_date.strftime('%Y%m%d')}_{chat_number:05d}"
        event_number = 0
        timestamp = datetime.combine(ingestion_date, time()) + timedelta(
            seconds=rng.randint(0, (20 * 60 * 60) - 1)
        )
        chat_events: list[dict[str, Any]] = []

        def add_event(event_type: str, agent_id: int | None, seconds_later: int) -> None:
            nonlocal event_number, timestamp
            timestamp += timedelta(seconds=seconds_later)
            event_number += 1
            chat_events.append(
                _new_event(
                    chat_id,
                    event_number,
                    event_type,
                    timestamp,
                    agent_id,
                    ingestion_date,
                )
            )

        add_event("chat_started", None, 0)

        if rng.random() < 0.08:
            if rng.random() < 0.45:
                add_event("customer_responded", None, rng.randint(15, 120))
            add_event("customer_closed_chat", None, rng.randint(20, 240))
        else:
            agent_id = rng.choice(AGENT_IDS)
            add_event("agent_assignment", agent_id, rng.randint(10, 90))

            for _ in range(rng.randint(0, 4)):
                if rng.random() < 0.54:
                    add_event("agent_responded", agent_id, rng.randint(20, 420))
                else:
                    add_event("customer_responded", None, rng.randint(20, 420))

            outcome = rng.random()
            if outcome < 0.14:
                add_event(
                    "chat_pushed_to_queue_due_inactivity",
                    agent_id,
                    rng.randint(120, 900),
                )
                add_event("system_closed_chat_after_inactivity", None, 60 * 60)
            elif outcome < 0.42:
                add_event("customer_closed_chat", None, rng.randint(30, 600))
            else:
                add_event("chat_closed_by_agent", agent_id, rng.randint(30, 600))

        skipped = rng.random() < 0.12
        customer_input = None
        if not skipped:
            customer_input = rng.choices(
                ["satisfied", "dissatisfied", None],
                weights=[70, 20, 10],
                k=1,
            )[0]
        surveys.append(
            {
                "survey_id": f"survey_{chat_id}",
                "chat_id": chat_id,
                "survey_skipped": skipped,
                "customer_input": customer_input,
            }
        )
        events.extend(chat_events)

    validate_generated_data(events, surveys)
    return events, surveys


def validate_generated_data(
    events: list[dict[str, Any]],
    surveys: list[dict[str, Any]],
) -> None:
    """Fail fast if simulated source data violates the documented contract."""
    if len({event["event_id"] for event in events}) != len(events):
        raise ValueError("event_id values must be unique")

    grouped: defaultdict[str, list[dict[str, Any]]] = defaultdict(list)
    for event in events:
        if event["event_type"] not in EVENT_TYPES:
            raise ValueError(f"Invalid event type: {event['event_type']}")
        grouped[str(event["chat_id"])].append(event)

    closed_chats: set[str] = set()
    for chat_id, chat_events in grouped.items():
        ordered = sorted(chat_events, key=lambda item: _timestamp(str(item["event_timestamp"])))
        if ordered[0]["event_type"] != "chat_started":
            raise ValueError(f"{chat_id} does not begin with chat_started")
        if sum(event["event_type"] == "chat_started" for event in ordered) != 1:
            raise ValueError(f"{chat_id} has an invalid number of starts")

        event_times = [_timestamp(str(event["event_timestamp"])) for event in ordered]
        if any(later <= earlier for earlier, later in zip(event_times, event_times[1:])):
            raise ValueError(f"{chat_id} event timestamps are not strictly increasing")

        assignments = [e for e in ordered if e["event_type"] == "agent_assignment"]
        if len(assignments) > 1:
            raise ValueError(f"{chat_id} has an agent reassignment")
        assigned_id = assignments[0]["agent_id"] if assignments else None
        assignment_time = _timestamp(assignments[0]["event_timestamp"]) if assignments else None

        for event in ordered:
            event_type = str(event["event_type"])
            agent_id = event["agent_id"]
            if event_type in NULL_AGENT_EVENTS and agent_id is not None:
                raise ValueError(f"{chat_id} has agent_id on {event_type}")
            if event_type in REQUIRED_AGENT_EVENTS and agent_id is None:
                raise ValueError(f"{chat_id} is missing agent_id on {event_type}")
            if agent_id is not None and assigned_id is not None and agent_id != assigned_id:
                raise ValueError(f"{chat_id} uses more than one agent_id")
            if event_type in REQUIRED_AGENT_EVENTS - {"agent_assignment"}:
                if assignment_time is None or _timestamp(event["event_timestamp"]) <= assignment_time:
                    raise ValueError(f"{chat_id} has agent activity before assignment")

        closures = [event for event in ordered if event["event_type"] in CLOSURE_EVENTS]
        if len(closures) != 1 or closures[0] is not ordered[-1]:
            raise ValueError(f"{chat_id} must end with one closure")
        closed_chats.add(chat_id)

        system_closures = [
            event for event in ordered
            if event["event_type"] == "system_closed_chat_after_inactivity"
        ]
        for closure in system_closures:
            pushed = [
                event for event in ordered
                if event["event_type"] == "chat_pushed_to_queue_due_inactivity"
            ]
            if not pushed or (
                _timestamp(closure["event_timestamp"])
                - _timestamp(pushed[-1]["event_timestamp"])
                != timedelta(hours=1)
            ):
                raise ValueError(f"{chat_id} inactivity closure is not one hour after push")

    if len({survey["survey_id"] for survey in surveys}) != len(surveys):
        raise ValueError("survey_id values must be unique")
    survey_chats = {str(survey["chat_id"]) for survey in surveys}
    if survey_chats != closed_chats or len(surveys) != len(survey_chats):
        raise ValueError("Every closed chat must have exactly one survey")
    for survey in surveys:
        value = survey["customer_input"]
        if survey["survey_skipped"] and value is not None:
            raise ValueError("Skipped surveys cannot contain customer_input")
        if value not in {"satisfied", "dissatisfied", None}:
            raise ValueError("Unexpected customer_input value")


def write_jsonl(
    ingestion_date: date,
    events: list[dict[str, Any]],
    surveys: list[dict[str, Any]],
    output_root: Path,
) -> tuple[Path, Path]:
    """Write a source-system daily delivery as JSON Lines files."""
    output_dir = output_root / ingestion_date.isoformat()
    output_dir.mkdir(parents=True, exist_ok=True)
    events_path = output_dir / "chat_logs.jsonl"
    surveys_path = output_dir / "surveys.jsonl"

    for path, rows in ((events_path, events), (surveys_path, surveys)):
        with path.open("w", encoding="utf-8") as handle:
            for row in rows:
                handle.write(json.dumps(row, sort_keys=True) + "\n")
    return events_path, surveys_path


def main() -> None:
    parser = argparse.ArgumentParser(description="Generate simulated daily chat source data.")
    parser.add_argument("--date", dest="ingestion_date", type=date.fromisoformat, default=date.today())
    parser.add_argument("--chat-count", type=int, default=250)
    parser.add_argument("--seed", type=int)
    parser.add_argument("--output-dir", type=Path, default=Path("data/generated"))
    args = parser.parse_args()

    events, surveys = generate_daily_data(args.ingestion_date, args.chat_count, args.seed)
    event_path, survey_path = write_jsonl(
        args.ingestion_date,
        events,
        surveys,
        args.output_dir,
    )
    print(f"Generated {len(events)} events for {len(surveys)} chats.")
    print(f"Events: {event_path}")
    print(f"Surveys: {survey_path}")


if __name__ == "__main__":
    main()

