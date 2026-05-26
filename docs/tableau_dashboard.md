# Tableau Live Dashboard Setup

## Connection

1. Start PostgreSQL and load at least one batch as described in the project README.
2. In Tableau, choose **Connect > PostgreSQL**.
3. Enter:

| Setting | Value |
| --- | --- |
| Server | `localhost` |
| Port | `5432` |
| Database | `chat_dashboard` |
| Username | `chat_admin` |
| Password | `chat_admin` |
| Connection type | Live |

Use the `reporting` schema rather than querying the raw event table directly.

## Tableau Data Sources

| View | Best Use |
| --- | --- |
| `reporting.v_chat_kpi_summary_daily` | KPI scorecards and trend lines |
| `reporting.v_agent_performance_daily` | Agent ranking and team comparison |
| `reporting.v_tableau_chat_detail` | Filters, drill-through, and closure analysis |

## Suggested Dashboard

Build KPI tiles for resolved chats, average first response minutes, first
response SLA percent, resolution SLA percent, and CSAT percent. Add a daily
trend using `chat_date`, a support-team comparison bar chart, and a closure
reason breakdown from the detail view.

Because the connection is live, Tableau reflects new fact rows after each
successful mart refresh without an extract refresh. The current batch runner
loads raw data only; execute `CALL raw.validate_source_data();` followed by
`CALL mart.refresh_star_schema();` before expecting newly loaded rows in the
dashboard.
