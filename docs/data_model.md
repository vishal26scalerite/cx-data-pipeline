# Data Model and Business Rules

## Pipeline Layers

| Layer | Objects | Purpose |
| --- | --- | --- |
| Source delivery | `data/generated/YYYY-MM-DD/*.jsonl` | Simulated daily operational extract |
| Raw | `raw.raw_chat_logs`, `raw.survey` | Immutable event and survey records |
| Quality gate | `raw.validate_source_data()` | SQL validation procedure before mart refresh |
| Dimensional mart | `mart.dim_*`, `mart.fact_chat_resolution` | Kimball star schema populated by refresh procedure |
| Presentation | `reporting.v_*` | Tableau live-connection views |

## Fact Grain

`mart.fact_chat_resolution` has exactly one row per closed chat with its related
survey. The fact supports response time, resolution time, SLA, CSAT, closure
reason, inactivity, agent, and team analysis.

## Dimensions

| Dimension | Key | Description |
| --- | --- | --- |
| `mart.dim_date` | `date_key` | Calendar attributes for the chat start date |
| `mart.dim_agent` | `agent_key` | Simulated agent and derived support team |
| `mart.dim_resolution_type` | `resolution_type_key` | Closure event classification |
| `mart.dim_survey_response` | `survey_response_key` | Satisfied, dissatisfied, no response, or skipped |

## SLA Definitions

| Measure | Definition |
| --- | --- |
| First response time | Time from `agent_assignment` to first `agent_responded` |
| First response SLA | First agent response within 5 minutes of assignment |
| Resolution time | Time from `chat_started` to closure |
| Resolution SLA | Closure within 60 minutes of chat start |
| CSAT | Satisfied responses divided by answered surveys |

## Enforced Source Rules

The generator and SQL procedure enforce the event vocabulary, event ordering,
single assignment, fixed assigned agent, no activity after closure, valid
inactivity closure timing, and one survey for every closed chat.

The generator validation runs during source creation. The database validation
and mart refresh procedures are implemented, but the active batch runner does
not yet call them automatically. After ingestion, run:

```powershell
docker compose exec postgres psql -U chat_admin -d chat_dashboard -c "CALL raw.validate_source_data(); CALL mart.refresh_star_schema();"
```

`system_closed_chat_after_inactivity` is modeled with `agent_id = NULL`
because it is performed by the system, while attribution still comes from the
preceding assignment event.

The supplied survey schema has no survey timestamp. The database can prove that
a survey belongs to a closed chat, but it cannot independently prove when the
survey was submitted. Adding `survey_timestamp` would allow that rule to be
fully audited in SQL.
