CREATE SCHEMA IF NOT EXISTS reporting;

CREATE OR REPLACE VIEW reporting.v_tableau_chat_detail AS
SELECT
    fact.chat_id,
    date_dim.full_date AS chat_date,
    date_dim.day_name,
    date_dim.month_name,
    date_dim.quarter_number,
    date_dim.year_number,
    COALESCE(agent.agent_id::TEXT, 'Unassigned') AS agent_id,
    COALESCE(agent.agent_name, 'Unassigned') AS agent_name,
    COALESCE(agent.support_team, 'Unassigned') AS support_team,
    resolution.resolution_label,
    survey.response_label AS survey_response,
    fact.started_at,
    fact.assigned_at,
    fact.first_agent_response_at,
    fact.closed_at,
    fact.first_response_seconds,
    ROUND(fact.first_response_seconds / 60.0, 2) AS first_response_minutes,
    fact.resolution_seconds,
    ROUND(fact.resolution_seconds / 60.0, 2) AS resolution_minutes,
    fact.agent_response_count,
    fact.customer_response_count,
    fact.pushed_due_to_inactivity,
    fact.first_response_sla_met,
    fact.resolution_sla_met,
    fact.satisfied_flag
FROM mart.fact_chat_resolution fact
JOIN mart.dim_date date_dim ON date_dim.date_key = fact.date_key
LEFT JOIN mart.dim_agent agent ON agent.agent_key = fact.agent_key
JOIN mart.dim_resolution_type resolution
  ON resolution.resolution_type_key = fact.resolution_type_key
JOIN mart.dim_survey_response survey
  ON survey.survey_response_key = fact.survey_response_key;

CREATE OR REPLACE VIEW reporting.v_chat_kpi_summary_daily AS
SELECT
    date_dim.full_date AS chat_date,
    COALESCE(agent.support_team, 'Unassigned') AS support_team,
    COUNT(*) AS resolved_chats,
    COUNT(*) FILTER (WHERE fact.agent_key IS NULL) AS unassigned_chats,
    COUNT(*) FILTER (WHERE fact.first_agent_response_at IS NOT NULL) AS responded_chats,
    ROUND(AVG(fact.first_response_seconds) / 60.0, 2) AS avg_first_response_minutes,
    ROUND(AVG(fact.resolution_seconds) / 60.0, 2) AS avg_resolution_minutes,
    ROUND(
        100.0 * COUNT(*) FILTER (WHERE fact.first_response_sla_met)
        / NULLIF(COUNT(*) FILTER (WHERE fact.first_response_sla_met IS NOT NULL), 0),
        2
    ) AS first_response_sla_pct,
    ROUND(
        100.0 * COUNT(*) FILTER (WHERE fact.resolution_sla_met)
        / NULLIF(COUNT(*), 0),
        2
    ) AS resolution_sla_pct,
    ROUND(
        100.0 * COUNT(*) FILTER (WHERE fact.satisfied_flag IS NOT NULL)
        / NULLIF(COUNT(*), 0),
        2
    ) AS survey_response_rate_pct,
    ROUND(
        100.0 * COUNT(*) FILTER (WHERE fact.satisfied_flag)
        / NULLIF(COUNT(*) FILTER (WHERE fact.satisfied_flag IS NOT NULL), 0),
        2
    ) AS csat_pct,
    COUNT(*) FILTER (WHERE fact.pushed_due_to_inactivity) AS inactivity_closures
FROM mart.fact_chat_resolution fact
JOIN mart.dim_date date_dim ON date_dim.date_key = fact.date_key
LEFT JOIN mart.dim_agent agent ON agent.agent_key = fact.agent_key
GROUP BY date_dim.full_date, COALESCE(agent.support_team, 'Unassigned');

CREATE OR REPLACE VIEW reporting.v_agent_performance_daily AS
SELECT
    date_dim.full_date AS chat_date,
    agent.agent_id,
    agent.agent_name,
    agent.support_team,
    COUNT(*) AS resolved_chats,
    ROUND(AVG(fact.first_response_seconds) / 60.0, 2) AS avg_first_response_minutes,
    ROUND(AVG(fact.resolution_seconds) / 60.0, 2) AS avg_resolution_minutes,
    ROUND(
        100.0 * COUNT(*) FILTER (WHERE fact.first_response_sla_met)
        / NULLIF(COUNT(*) FILTER (WHERE fact.first_response_sla_met IS NOT NULL), 0),
        2
    ) AS first_response_sla_pct,
    ROUND(
        100.0 * COUNT(*) FILTER (WHERE fact.satisfied_flag)
        / NULLIF(COUNT(*) FILTER (WHERE fact.satisfied_flag IS NOT NULL), 0),
        2
    ) AS csat_pct
FROM mart.fact_chat_resolution fact
JOIN mart.dim_date date_dim ON date_dim.date_key = fact.date_key
JOIN mart.dim_agent agent ON agent.agent_key = fact.agent_key
GROUP BY
    date_dim.full_date,
    agent.agent_id,
    agent.agent_name,
    agent.support_team;

