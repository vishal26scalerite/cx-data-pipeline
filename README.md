# Customer Service Chat Analytics Dashboard Pipeline

This project simulates daily customer service chat events and post-chat
surveys, loads them into PostgreSQL, validates the operational rules in SQL,
and transforms closed conversations into a Kimball star schema for a Tableau
live dashboard.

## Architecture

```text
Daily JSONL source files -> raw tables -> SQL quality gate -> Kimball mart -> reporting views -> Tableau Live
```

PostgreSQL is used because Tableau can connect to it directly and keep the
dashboard live as new daily batches are loaded.

## Project Contents

| Path | Description |
| --- | --- |
| `pipeline/generate_data.py` | Deterministic simulated chat and survey source generator |
| `pipeline/run_daily_batch.py` | Daily generation, ingestion, validation, and mart refresh |
| `sql/001_raw_layer.sql` | Raw tables and source-rule quality procedure |
| `sql/002_star_schema.sql` | Dimensions, fact table, and refresh procedure |
| `sql/003_reporting_views.sql` | Tableau-facing views |
| `docs/data_model.md` | Fact grain, dimensions, SLAs, and modeling decisions |
| `docs/tableau_dashboard.md` | Tableau live connection and dashboard layout |

## Quick Start With Docker

Docker is the only local runtime required for this path.

```powershell
docker compose up -d postgres
docker compose build pipeline
docker compose run --rm pipeline --date 2026-05-25 --chat-count 500 --seed 20260525
```

The first build may download the PostgreSQL and Python container images. The
pipeline command generates JSONL under `data/generated/2026-05-25`, inserts
the raw records, applies SQL checks, and refreshes the mart.

Run another daily batch to add dashboard data:

```powershell
docker compose run --rm pipeline --date 2026-05-26 --chat-count 500 --seed 20260526
```

The identifiers are deterministic by source date. Re-running the same date
with the same seed is idempotent; use a new date for a new simulated delivery.

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

SQL validation also runs on every loaded batch through
`raw.validate_source_data()`. A rule violation aborts the transaction before
facts or reporting views are refreshed.

