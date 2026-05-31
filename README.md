# Customer Service Chat Analytics Dashboard Pipeline

This project simulates daily customer service chat events and post-chat
surveys, loads them into PostgreSQL, and provides SQL procedures and reporting
views for a customer-service analytics dashboard.

For a complete implementation snapshot, runbook, metrics reference, and known
gaps, see [`docs/project_documentation.md`](docs/project_documentation.md).

## Architecture

```text
Generated chats -> optional JSONL files -> raw tables -> SQL quality gate -> Kimball mart -> reporting views -> dashboard
```

PostgreSQL is used because Tableau can connect to it directly and keep the
dashboard live as the mart is refreshed with new daily data.

## Project Contents

| Path | Description |
| --- | --- |
| `pipeline/generate_data.py` | Deterministic simulated chat and survey source generator |
| `pipeline/run_daily_batch.py` | Single-day, date-range, and fast-simulation raw ingestion runner |
| `sql/001_raw_layer.sql` | Raw tables and source-rule quality procedure |
| `sql/002_star_schema.sql` | Dimensions, fact table, and refresh procedure |
| `sql/003_reporting_views.sql` | Dashboard-facing views |
| `docs/project_documentation.md` | Current build status, operations runbook, metrics, and gaps |
| `docs/data_model.md` | Fact grain, dimensions, SLAs, and modeling decisions |
| `docs/tableau_dashboard.md` | Tableau live connection and dashboard layout |
| `docs/metabase_dashboard.md` | Local Metabase connection and dashboard layout |

## Quick Start With Docker

Docker is the only local runtime required for this path.

```powershell
docker compose up -d postgres
docker compose build pipeline
docker compose run --rm pipeline --date 2026-05-25 --chat-count 500 --seed 20260525
```

The first build may download the PostgreSQL and Python container images. The
pipeline command generates JSONL under `data/generated/2026-05-25`, inserts
the raw records, validates the source data, and refreshes the reporting mart.

Run another daily batch to add dashboard data:

```powershell
docker compose run --rm pipeline --date 2026-05-26 --chat-count 500 --seed 20260526
```

The identifiers are deterministic by source date. Re-running the same date
with the same seed replaces the date's raw data without duplicate chat rows;
the batch-run log still records each execution. Use a new date for a new
simulated delivery.

Load a range or quickly simulate recent history:

```powershell
# Load an explicit date range:
docker compose run --rm pipeline --start-date 2026-05-01 --end-date 2026-05-25 --chat-count 500 --seed 20260501

# Or load without writing JSONL files:
docker compose run --rm pipeline --start-date 2026-05-01 --end-date 2026-05-25 --chat-count 500 --seed 20260501 --skip-backups

# Or simulate the most recent 30 days without JSONL files:
docker compose run --rm pipeline --fast-sim-days 30 --chat-count 500
```

`--skip-backups` and `--fast-sim-days` skip JSONL files. The runner validates
and refreshes the mart once after all requested dates are loaded.

## Local Python Alternative

With Python 3.11+ installed, start only PostgreSQL with Docker and run:

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
$env:DATABASE_URL = "postgresql://chat_admin:chat_admin@localhost:5432/chat_dashboard"
python -m pipeline.run_daily_batch --date 2026-05-25 --chat-count 500 --seed 20260525
```

Generate source files without loading PostgreSQL:

```powershell
python -m pipeline.generate_data --date 2026-05-25 --chat-count 25 --seed 7
```

## Star Schema

The mart fact grain is one row per closed chat:

| Table | Purpose |
| --- | --- |
| `mart.fact_chat_resolution` | Duration, SLA, response counts, inactivity, and CSAT flags |
| `mart.dim_date` | Calendar reporting by chat start date |
| `mart.dim_agent` | Simulated agent and support team |
| `mart.dim_resolution_type` | Agent, customer, or inactivity closure |
| `mart.dim_survey_response` | Survey answer state |

## Tableau Connection

Use a PostgreSQL **Live** connection to `localhost:5432`, database
`chat_dashboard`, with username and password `chat_admin`. Select the
`reporting` schema and begin with:

- `reporting.v_chat_kpi_summary_daily`
- `reporting.v_agent_performance_daily`
- `reporting.v_tableau_chat_detail`

Full worksheet recommendations are in `docs/tableau_dashboard.md`.

## Verification

Generator rule tests do not require a database:

```powershell
python -m unittest discover -s tests -v
```

The batch runner automatically calls `raw.validate_source_data()` before
`mart.refresh_star_schema()`. If you load raw data outside the runner, call
those procedures manually before using the dashboard views.
