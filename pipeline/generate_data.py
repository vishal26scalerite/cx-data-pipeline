"""Generate deterministic daily chat events and survey source files."""

from __future__ import annotations

import argparse
import json
import random
from collections import defaultdict, deque
from dataclasses import dataclass, field
from datetime import date, datetime, time, timedelta
from pathlib import Path
from typing import Any


EVENT_TYPES = {
    "chat_started",
    "chat_entered_queue",
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
    "chat_entered_queue",
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
MAX_AGENT_CAPACITY = 2
ARRIVAL_START_TIME = time(hour=8)
ARRIVAL_WINDOW_SECONDS = 12 * 60 * 60


@dataclass
class ChatState:
    chat_id: str
    started_at: datetime
    ingestion_date: date
    status: str = "new"
    agent_id: int | None = None
    event_number: int = 0
    close_at: datetime | None = None
    abandon_at: datetime | None = None
    events: list[dict[str, Any]] = field(default_factory=list)


@dataclass
class AgentState:
    agent_id: int
    max_capacity: int = MAX_AGENT_CAPACITY
    active_chats: set[str] = field(default_factory=set)

    @property
    def available_slots(self) -> int:
        return self.max_capacity - len(self.active_chats)


@dataclass
class SimulationState:
    waiting_queue: deque[ChatState] = field(default_factory=deque)
    active_chats: dict[str, ChatState] = field(default_factory=dict)
    agents: dict[int, AgentState] = field(
        default_factory=lambda: {
            agent_id: AgentState(agent_id=agent_id) for agent_id in AGENT_IDS
        }
    )
    event_stream: list[dict[str, Any]] = field(default_factory=list)
    surveys: list[dict[str, Any]] = field(default_factory=list)

    def add_event(
        self,
        chat: ChatState,
        event_type: str,
        event_timestamp: datetime,
        agent_id: int | None,
    ) -> None:
        chat.event_number += 1
        event = _new_event(
            chat.chat_id,
            chat.event_number,
            event_type,
            event_timestamp,
            agent_id,
            chat.ingestion_date,
        )
        chat.events.append(event)
        self.event_stream.append(event)


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
    """Return queue- and capacity-aware raw events and surveys for one day."""
    if chat_count < 1:
        raise ValueError("chat_count must be positive")

    effective_seed = seed if seed is not None else int(ingestion_date.strftime("%Y%m%d"))
    rng = random.Random(effective_seed)
    state = SimulationState()
    arrivals = _generate_arrivals(ingestion_date, chat_count, rng)
    arrival_index = 0

    while arrival_index < len(arrivals) or state.active_chats or state.waiting_queue:
        current_time = min(
            timestamp
            for timestamp in (
                arrivals[arrival_index].started_at if arrival_index < len(arrivals) else None,
                _next_closure_time(state),
                _next_abandon_time(state),
            )
            if timestamp is not None
        )

        _release_closed_chats(state, current_time)
        _close_abandoned_waiting_chats(state, current_time, rng)

        while arrival_index < len(arrivals) and arrivals[arrival_index].started_at <= current_time:
            chat = arrivals[arrival_index]
            _start_chat(state, chat, rng)
            arrival_index += 1

        _assign_waiting_chats(state, rng, current_time)

    events = sorted(
        state.event_stream,
        key=lambda event: (_timestamp(str(event["event_timestamp"])), str(event["event_id"])),
    )
    validate_generated_data(events, state.surveys)
    return events, state.surveys


def _generate_arrivals(
    ingestion_date: date,
    chat_count: int,
    rng: random.Random,
) -> list[ChatState]:
    arrival_start = datetime.combine(ingestion_date, ARRIVAL_START_TIME)
    arrivals = [
        ChatState(
            chat_id=f"chat_{ingestion_date.strftime('%Y%m%d')}_{chat_number:05d}",
            started_at=arrival_start + timedelta(seconds=rng.randint(0, ARRIVAL_WINDOW_SECONDS - 1)),
            ingestion_date=ingestion_date,
        )
        for chat_number in range(1, chat_count + 1)
    ]
    return sorted(arrivals, key=lambda chat: (chat.started_at, chat.chat_id))


def _start_chat(state: SimulationState, chat: ChatState, rng: random.Random) -> None:
    chat.status = "queued"
    state.add_event(chat, "chat_started", chat.started_at, None)
    queue_time = chat.started_at + timedelta(seconds=1)
    state.add_event(chat, "chat_entered_queue", queue_time, None)
    if rng.random() < 0.04:
        chat.abandon_at = queue_time + timedelta(seconds=rng.randint(120, 900))
    state.waiting_queue.append(chat)


def _next_closure_time(state: SimulationState) -> datetime | None:
    close_times = [
        chat.close_at
        for chat in state.active_chats.values()
        if chat.close_at is not None
    ]
    return min(close_times) if close_times else None


def _next_abandon_time(state: SimulationState) -> datetime | None:
    abandon_times = [
        chat.abandon_at
        for chat in state.waiting_queue
        if chat.abandon_at is not None
    ]
    return min(abandon_times) if abandon_times else None


def _available_agent(state: SimulationState) -> AgentState | None:
    available_agents = [
        agent
        for agent in state.agents.values()
        if agent.available_slots > 0
    ]
    if not available_agents:
        return None
    return min(available_agents, key=lambda agent: (len(agent.active_chats), agent.agent_id))


def _release_closed_chats(state: SimulationState, current_time: datetime) -> None:
    closed_chat_ids = [
        chat_id
        for chat_id, chat in state.active_chats.items()
        if chat.close_at is not None and chat.close_at <= current_time
    ]
    for chat_id in closed_chat_ids:
        chat = state.active_chats.pop(chat_id)
        if chat.agent_id is not None:
            state.agents[chat.agent_id].active_chats.discard(chat_id)


def _close_abandoned_waiting_chats(
    state: SimulationState,
    current_time: datetime,
    rng: random.Random,
) -> None:
    remaining_queue: deque[ChatState] = deque()
    for chat in state.waiting_queue:
        if chat.abandon_at is not None and chat.abandon_at <= current_time:
            chat.status = "closed"
            if rng.random() < 0.45:
                response_time = chat.events[-1]["event_timestamp"]
                state.add_event(
                    chat,
                    "customer_responded",
                    _timestamp(str(response_time)) + timedelta(seconds=rng.randint(15, 90)),
                    None,
                )
            state.add_event(chat, "customer_closed_chat", chat.abandon_at, None)
            _add_survey(state, chat, rng)
        else:
            remaining_queue.append(chat)
    state.waiting_queue = remaining_queue


def _assign_waiting_chats(
    state: SimulationState,
    rng: random.Random,
    current_time: datetime,
) -> None:
    while state.waiting_queue:
        agent = _available_agent(state)
        if agent is None:
            return

        chat = state.waiting_queue.popleft()
        assignment_time = max(
            current_time + timedelta(seconds=1),
            _timestamp(str(chat.events[-1]["event_timestamp"])) + timedelta(seconds=1),
        )
        if chat.abandon_at is not None and chat.abandon_at <= assignment_time:
            state.add_event(chat, "customer_closed_chat", chat.abandon_at, None)
            _add_survey(state, chat, rng)
            continue

        chat.status = "active"
        chat.agent_id = agent.agent_id
        agent.active_chats.add(chat.chat_id)
        state.active_chats[chat.chat_id] = chat
        state.add_event(chat, "agent_assignment", assignment_time, agent.agent_id)
        _generate_active_chat_events(state, chat, rng, assignment_time)


def _generate_active_chat_events(
    state: SimulationState,
    chat: ChatState,
    rng: random.Random,
    assignment_time: datetime,
) -> None:
    timestamp = assignment_time
    agent_id = chat.agent_id
    if agent_id is None:
        raise ValueError(f"{chat.chat_id} cannot generate active events without an agent")

    for _ in range(rng.randint(0, 4)):
        timestamp += timedelta(seconds=rng.randint(20, 420))
        if rng.random() < 0.54:
            state.add_event(chat, "agent_responded", timestamp, agent_id)
        else:
            state.add_event(chat, "customer_responded", timestamp, None)

    outcome = rng.random()
    if outcome < 0.14:
        timestamp += timedelta(seconds=rng.randint(120, 900))
        state.add_event(chat, "chat_pushed_to_queue_due_inactivity", timestamp, agent_id)
        timestamp += timedelta(hours=1)
        state.add_event(chat, "system_closed_chat_after_inactivity", timestamp, None)
    elif outcome < 0.42:
        timestamp += timedelta(seconds=rng.randint(30, 600))
        state.add_event(chat, "customer_closed_chat", timestamp, None)
    else:
        timestamp += timedelta(seconds=rng.randint(30, 600))
        state.add_event(chat, "chat_closed_by_agent", timestamp, agent_id)

    chat.close_at = timestamp
    _add_survey(state, chat, rng)


def _add_survey(state: SimulationState, chat: ChatState, rng: random.Random) -> None:
    skipped = rng.random() < 0.12
    customer_input = None
    if not skipped:
        customer_input = rng.choices(
            ["satisfied", "dissatisfied", None],
            weights=[70, 20, 10],
            k=1,
        )[0]
    state.surveys.append(
        {
            "survey_id": f"survey_{chat.chat_id}",
            "chat_id": chat.chat_id,
            "survey_skipped": skipped,
            "customer_input": customer_input,
        }
    )


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
    agent_capacity_changes: defaultdict[int, list[tuple[datetime, int, str]]] = defaultdict(list)
    for chat_id, chat_events in grouped.items():
        ordered = sorted(chat_events, key=lambda item: _timestamp(str(item["event_timestamp"])))
        if ordered[0]["event_type"] != "chat_started":
            raise ValueError(f"{chat_id} does not begin with chat_started")
        if sum(event["event_type"] == "chat_started" for event in ordered) != 1:
            raise ValueError(f"{chat_id} has an invalid number of starts")

        event_times = [_timestamp(str(event["event_timestamp"])) for event in ordered]
        if any(later <= earlier for earlier, later in zip(event_times, event_times[1:])):
            raise ValueError(f"{chat_id} event timestamps are not strictly increasing")

        queue_events = [event for event in ordered if event["event_type"] == "chat_entered_queue"]
        if len(queue_events) != 1:
            raise ValueError(f"{chat_id} must enter the queue exactly once")
        queue_time = _timestamp(str(queue_events[0]["event_timestamp"]))
        if queue_time <= event_times[0]:
            raise ValueError(f"{chat_id} enters queue before chat_started")

        assignments = [e for e in ordered if e["event_type"] == "agent_assignment"]
        if len(assignments) > 1:
            raise ValueError(f"{chat_id} has an agent reassignment")
        assigned_id = assignments[0]["agent_id"] if assignments else None
        assignment_time = _timestamp(assignments[0]["event_timestamp"]) if assignments else None
        if assignment_time is not None and assignment_time <= queue_time:
            raise ValueError(f"{chat_id} is assigned before entering the queue")

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
        closure_time = _timestamp(str(closures[0]["event_timestamp"]))

        if assigned_id is not None and assignment_time is not None:
            agent_capacity_changes[int(assigned_id)].append((assignment_time, 1, chat_id))
            agent_capacity_changes[int(assigned_id)].append((closure_time, -1, chat_id))

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

    for agent_id, changes in agent_capacity_changes.items():
        active_count = 0
        for event_time, delta, chat_id in sorted(changes, key=lambda item: (item[0], item[1])):
            active_count += delta
            if active_count > MAX_AGENT_CAPACITY:
                raise ValueError(
                    f"Agent {agent_id} exceeds capacity {MAX_AGENT_CAPACITY} at "
                    f"{event_time.isoformat(sep=' ')} while processing {chat_id}"
                )

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
