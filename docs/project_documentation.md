# Customer Service Chat Analytics Dashboard

## Implementation Snapshot

This document records the system implemented in the repository as of
2026-05-27. The project generates simulated customer-service chats and survey
responses, loads them into PostgreSQL, models closed chats for analysis, and
exposes reporting views intended for Tableau or Metabase dashboards.

## Current Status

| Capability | Status | Implementation |
| --- | --- | --- |
| Deterministic queue/capacity source generation | Implemented | `pipeline/generate_data.py` |
| JSONL source-file delivery | Implemented for normal and date-range runs unless `--skip-backups` is used | `data/generated/YYYY-MM-DD/` |
| Single-day raw ingestion | Implemented | `pipeline/run_daily_batch.py` |
| Date-range raw ingestion | Implemented | `--start-date` and `--end-date` |
| Fast multi-day raw ingestion | Implemented | `--fast-sim-days`; skips JSONL output |
| PostgreSQL raw schema and constraints | Implemented | `sql/001_raw_layer.sql` |
| SQL quality procedure | Implemented and called by the active runner | `raw.validate_source_data()` |
| Star-schema refresh procedure | Implemented and called by the active runner | `mart.refresh_star_schema()` |
| Reporting views | Implemented; populated after a mart refresh | `sql/003_reporting_views.sql` |
| Tableau dashboard design | Documented | `docs/tableau_dashboard.md` |
| Metabase local dashboard setup | Documented and containerized | `docs/metabase_dashboard.md` |
| Unit and integration tests | Implemented | `tests/test_generate_data.py`, `tests/test_run_daily_batch.py`, `tests/test_star_schema_sql.py`, `tests/test_postgres_integration.py` |

The active batch runner generates source rows, loads raw data, validates the
loaded source contract, and refreshes the mart once after all requested dates
are processed.

## Architecture

```text
pipeline.generate_data
        |
        +--> JSONL daily files (normal/date-range runs)
        |
        v
PostgreSQL raw.raw_chat_logs + raw.survey + raw.batch_run_log
        |
        |  CALL raw.validate_source_data()
        v
validated raw data
        |  CALL mart.refresh_star_schema()
        v
PostgreSQL mart dimensions + mart.fact_chat_resolution
        |
        v
reporting views
        |
        +--> Tableau Live dashboard
        +--> Metabase dashboard
```

## Technology Stack

| Component | Technology | Purpose |
| --- | --- | --- |
| Batch application | Python 3.12, `psycopg` | Generate data and stream it into PostgreSQL |
| Database | PostgreSQL 16 | Persist raw events, model facts/dimensions, expose views |
| Local orchestration | Docker Compose | Run PostgreSQL, pipeline jobs, and optional Metabase |
| Dashboard options | Tableau Live or Metabase | Visualize operational performance metrics |
| Tests | Python `unittest` | Validate generation rules, batch orchestration, SQL refresh behavior, and PostgreSQL pipeline integration |

## Repository Layout

| Path | Purpose |
| --- | --- |
| `pipeline/generate_data.py` | Creates deterministic queue/capacity-aware chats and survey rows and validates the generated contract |
| `pipeline/db.py` | Creates database objects, loads raw rows with PostgreSQL `COPY`, and defines analytics refresh calls |
| `pipeline/run_daily_batch.py` | Command-line runner for single-day, date-range, and fast-simulation ingestion |
| `sql/001_raw_layer.sql` | Raw schemas, constraints, batch log, and validation procedure |
| `sql/002_star_schema.sql` | Dimensions, resolution fact, SLA derivation, and mart refresh procedure |
| `sql/003_reporting_views.sql` | Dashboard-facing detail, KPI, and agent performance views |
| `docs/data_model.md` | Data-model and business-rule reference |
| `docs/tableau_dashboard.md` | Tableau connection and dashboard guidance |
| `docs/metabase_dashboard.md` | Local Metabase deployment and dashboard guidance |
| `tests/test_generate_data.py` | Generator and JSONL unit tests |
| `tests/test_run_daily_batch.py` | Batch runner orchestration unit tests |
| `tests/test_star_schema_sql.py` | Mart refresh SQL regression tests |
| `tests/test_postgres_integration.py` | PostgreSQL generate-load-validate-refresh reporting integration test |

## Data Generation

The generator uses explicit simulation state objects for a waiting queue,
active chats, an agent registry, and a chronological event stream. Each agent
can hold at most two active chats at once. Each generated chat begins with
`chat_started`, enters the queue with `chat_entered_queue`, and ends in exactly
one closure outcome:

| Closure Outcome | Event |
| --- | --- |
| Resolved by agent | `chat_closed_by_agent` |
| Ended by customer | `customer_closed_chat` |
| Timed out after inactivity | `system_closed_chat_after_inactivity` |

Queued chats are assigned only when an agent has capacity; a small share can be
closed by the customer before assignment. Assigned chats can contain agent and
customer responses. For inactivity closures,
`chat_pushed_to_queue_due_inactivity` occurs exactly one hour before system
closure. Each closed chat receives one survey record with a state of satisfied,
dissatisfied, no response, or skipped.

Identifiers and generated values are deterministic for a source date and seed.
For date ranges, an explicitly supplied base seed is incremented once per
processed day.

### JSONL Outputs

For a normal run, the pipeline writes:

```text
data/generated/YYYY-MM-DD/chat_logs.jsonl
data/generated/YYYY-MM-DD/surveys.jsonl
```

`--skip-backups` bypasses these JSONL files for single-day and date-range runs.
`--fast-sim-days` also bypasses JSONL files and loads in-memory rows directly
into PostgreSQL.

## Database Model

### Raw Layer

| Table | Grain | Purpose |
| --- | --- | --- |
| `raw.raw_chat_logs` | One row per chat event | Operational event stream |
| `raw.survey` | One row per chat survey | Post-chat customer response |
| `raw.batch_run_log` | One row per ingestion execution/date | Load audit record |

For a source date reload, the loader deletes existing raw chat and survey rows
for that date and re-inserts the newly generated rows using PostgreSQL `COPY`.
The batch log records each execution, including reruns.

### Mart Layer

The fact grain is one row per closed chat with its linked survey.

| Object | Purpose |
| --- | --- |
| `mart.fact_chat_resolution` | Queue wait, durations, response counts, SLA flags, inactivity, and satisfaction |
| `mart.dim_date` | Calendar reporting attributes |
| `mart.dim_agent` | Agent and derived support team |
| `mart.dim_resolution_type` | Closure classifications |
| `mart.dim_survey_response` | Satisfaction, non-response, and skipped survey classifications |

The refresh procedure synchronizes the fact table to the current raw
closed-chat set. Replacing a source date with fewer chats removes facts for
chats that are no longer present in raw data.

### Reporting Views

| View | Intended Use |
| --- | --- |
| `reporting.v_tableau_chat_detail` | Chat-level detail, filters, and drill-through |
| `reporting.v_chat_kpi_summary_daily` | Daily/team KPI cards and trends |
| `reporting.v_agent_performance_daily` | Agent comparison and ranking |

## Metrics and Business Rules

| Metric | Calculation |
| --- | --- |
| Queue wait time | `agent_assignment` timestamp minus `chat_entered_queue` timestamp; null for chats closed before assignment |
| First response time | First `agent_responded` timestamp minus `agent_assignment` timestamp |
| First response SLA | First response occurs within 5 minutes of assignment |
| Resolution time | Closure timestamp minus `chat_started` timestamp |
| Resolution SLA | Closure occurs within 60 minutes of chat start |
| CSAT | Satisfied answers divided by answered survey responses |
| Inactivity closures | Chats with `chat_pushed_to_queue_due_inactivity` |
| Agent capacity | No generated agent has more than two active assigned chats at once |

The Python generator validates its own output before files or database rows are
created. PostgreSQL also includes a deeper validation procedure for event
ordering, agent assignment consistency, inactivity timing, closure behavior,
and closed-chat-to-survey matching. The batch runner calls that procedure
before refreshing the mart; call it manually only when loading raw data outside
the runner.

## Runbook

### Prerequisites

- Docker Desktop with Docker Compose for the standard local setup.
- Tableau Desktop/Cloud access or a browser for optional Metabase dashboards.
- Python 3.11+ only when using the local Python path instead of the pipeline
  container.

### Start PostgreSQL and Load One Day

```powershell
docker compose up -d postgres
docker compose build pipeline
docker compose run --rm pipeline --date 2026-05-25 --chat-count 500 --seed 20260525
```

### Load a Date Range

```powershell
docker compose run --rm pipeline --start-date 2026-05-01 --end-date 2026-05-25 --chat-count 500 --seed 20260501
```

### Generate Fast Simulation History

The command below generates the most recent 30 days relative to the runtime
date and skips daily JSONL output.

```powershell
docker compose run --rm pipeline --fast-sim-days 30 --chat-count 500
```

### Run With Local Python

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
$env:DATABASE_URL = "postgresql://chat_admin:chat_admin@localhost:5432/chat_dashboard"
python -m pipeline.run_daily_batch --date 2026-05-25 --chat-count 500 --seed 20260525
```

## Dashboard Access

### Metabase

Start the optional local Metabase service:

```powershell
docker compose -f docker-compose.yml -f docker-compose.metabase.yml up -d postgres metabase
```

Browse to `http://localhost:3000`, add PostgreSQL using host `postgres`,
database `chat_dashboard`, and the default `chat_admin` credentials, then
build cards from the `reporting` views.

### Tableau

Connect Tableau to PostgreSQL on `localhost:5432`, database `chat_dashboard`,
username `chat_admin`, password `chat_admin`, with a live connection. Use the
`reporting` schema rather than querying the raw event stream.

## Verification

Generator unit tests:

```powershell
python -m unittest discover -s tests -v
```

Database validation after any ingestion run:

```powershell
docker compose exec postgres psql -U chat_admin -d chat_dashboard -c "CALL raw.validate_source_data();"
```

Dashboard readiness check:

```powershell
docker compose exec postgres psql -U chat_admin -d chat_dashboard -c "SELECT COUNT(*) AS fact_rows FROM mart.fact_chat_resolution; SELECT COUNT(*) AS daily_kpi_rows FROM reporting.v_chat_kpi_summary_daily;"
```

PostgreSQL integration test:

```powershell
docker compose run --rm --entrypoint python --volume "C:\Users\ASUS\chat dashboard project:/app" pipeline -m unittest tests.test_postgres_integration -v
```

## Known Gaps and Next Work

| Gap | Effect | Recommended Completion |
| --- | --- | --- |
| `pipeline/run_daily_batch - Copy.py` remains in the repository | Two batch scripts can cause confusion | Remove or archive it after confirming it is no longer needed |
| PostgreSQL integration test covers the happy path only | Edge cases such as invalid source rows and stale-date reloads still rely on focused tests/manual checks | Add targeted integration scenarios as the simulator grows |
| Survey rows do not include a submission timestamp | Survey-after-closure timing cannot be audited | Add `survey_timestamp` if that rule is required |
