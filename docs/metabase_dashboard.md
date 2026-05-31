# Metabase Dashboard Setup

Metabase is the free, locally hosted presentation layer for this project. It
connects directly to the PostgreSQL star schema and reporting views, so a new
mart refresh is available to dashboard queries without publishing an extract.

## Start Metabase

From the project directory:

```powershell
docker compose -f docker-compose.yml -f docker-compose.metabase.yml up -d postgres metabase
```

Open `http://localhost:3000` and complete the first-time administrator setup.

## Connect to PostgreSQL

In the Metabase database setup screen, enter:

| Setting | Value |
| --- | --- |
| Database type | PostgreSQL |
| Display name | Chat Dashboard Mart |
| Host | `postgres` |
| Port | `5432` |
| Database name | `chat_dashboard` |
| Username | `chat_admin` |
| Password | `chat_admin` |
| SSL | Off |

The host is `postgres`, rather than `localhost`, because Metabase and
PostgreSQL run as services on the same Docker Compose network.

## Reporting Views

Use these views from the `reporting` schema for dashboard questions:

| View | Use |
| --- | --- |
| `v_chat_kpi_summary_daily` | KPI cards and daily or team trend charts |
| `v_agent_performance_daily` | Agent comparison table and ranking charts |
| `v_tableau_chat_detail` | Resolution type, SLA, CSAT, and drill-through detail |

## Recommended Cards

Create a dashboard named **Customer Service Chat Operations Dashboard** with:

| Card | Data Source | Visualization |
| --- | --- | --- |
| Resolved Chats | `v_chat_kpi_summary_daily` sum of `resolved_chats` | Number |
| Average First Response | `v_chat_kpi_summary_daily` weighted or detail-view average | Number |
| Resolution SLA % | `v_tableau_chat_detail` percent of `resolution_sla_met` | Number |
| CSAT % | `v_tableau_chat_detail` percent satisfied among answered surveys | Number |
| Resolved Chats by Team | `v_chat_kpi_summary_daily` by `support_team` | Bar |
| Daily Chat Volume | `v_chat_kpi_summary_daily` by `chat_date` | Line |
| Closure Reason Breakdown | `v_tableau_chat_detail` by `resolution_label` | Donut or bar |
| Agent Performance | `v_agent_performance_daily` | Table |

Add dashboard filters for `chat_date`, `support_team`, and `agent_name`.

## Daily Update

Run another daily delivery:

```powershell
docker compose run --rm pipeline --date 2026-05-26 --chat-count 500 --seed 20260526
```

The batch runner validates the new raw data and refreshes the reporting mart.
Refresh the Metabase dashboard page after the pipeline completes.
