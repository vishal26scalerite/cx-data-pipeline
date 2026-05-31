CREATE SCHEMA IF NOT EXISTS mart;

CREATE TABLE IF NOT EXISTS mart.dim_date (
    date_key INTEGER PRIMARY KEY,
    full_date DATE NOT NULL UNIQUE,
    day_of_week SMALLINT NOT NULL,
    day_name TEXT NOT NULL,
    month_number SMALLINT NOT NULL,
    month_name TEXT NOT NULL,
    quarter_number SMALLINT NOT NULL,
    year_number SMALLINT NOT NULL,
    is_weekend BOOLEAN NOT NULL
);

CREATE TABLE IF NOT EXISTS mart.dim_agent (
    agent_key INTEGER GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    agent_id INTEGER NOT NULL UNIQUE,
    agent_name TEXT NOT NULL,
    support_team TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS mart.dim_resolution_type (
    resolution_type_key INTEGER GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    resolution_code TEXT NOT NULL UNIQUE,
    resolution_label TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS mart.dim_survey_response (
    survey_response_key INTEGER GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    response_code TEXT NOT NULL UNIQUE,
    response_label TEXT NOT NULL,
    is_answered BOOLEAN NOT NULL
);

CREATE TABLE IF NOT EXISTS mart.fact_chat_resolution (
    chat_fact_key BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    chat_id TEXT NOT NULL UNIQUE,
    date_key INTEGER NOT NULL REFERENCES mart.dim_date (date_key),
    agent_key INTEGER REFERENCES mart.dim_agent (agent_key),
    resolution_type_key INTEGER NOT NULL REFERENCES mart.dim_resolution_type (resolution_type_key),
    survey_response_key INTEGER NOT NULL REFERENCES mart.dim_survey_response (survey_response_key),
    started_at TIMESTAMP NOT NULL,
    entered_queue_at TIMESTAMP,
    assigned_at TIMESTAMP,
    first_agent_response_at TIMESTAMP,
    closed_at TIMESTAMP NOT NULL,
    ingestion_date DATE NOT NULL,
    queue_wait_seconds INTEGER,
    first_response_seconds INTEGER,
    resolution_seconds INTEGER NOT NULL,
    agent_response_count INTEGER NOT NULL,
    customer_response_count INTEGER NOT NULL,
    pushed_due_to_inactivity BOOLEAN NOT NULL,
    first_response_sla_met BOOLEAN,
    resolution_sla_met BOOLEAN NOT NULL,
    satisfied_flag BOOLEAN,
    CONSTRAINT fact_chat_resolution_queue_wait_seconds_ck CHECK (
        queue_wait_seconds IS NULL OR queue_wait_seconds >= 0
    ),
    CONSTRAINT fact_chat_resolution_first_response_seconds_ck CHECK (
        first_response_seconds IS NULL OR first_response_seconds >= 0
    ),
    CONSTRAINT fact_chat_resolution_resolution_seconds_ck CHECK (resolution_seconds >= 0)
);

CREATE INDEX IF NOT EXISTS fact_chat_resolution_date_idx
    ON mart.fact_chat_resolution (date_key);
CREATE INDEX IF NOT EXISTS fact_chat_resolution_agent_idx
    ON mart.fact_chat_resolution (agent_key);

ALTER TABLE mart.fact_chat_resolution
    ADD COLUMN IF NOT EXISTS entered_queue_at TIMESTAMP;
ALTER TABLE mart.fact_chat_resolution
    ADD COLUMN IF NOT EXISTS queue_wait_seconds INTEGER;

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1
        FROM pg_constraint
        WHERE conname = 'fact_chat_resolution_queue_wait_seconds_ck'
          AND conrelid = 'mart.fact_chat_resolution'::REGCLASS
    ) THEN
        ALTER TABLE mart.fact_chat_resolution
            ADD CONSTRAINT fact_chat_resolution_queue_wait_seconds_ck CHECK (
                queue_wait_seconds IS NULL OR queue_wait_seconds >= 0
            );
    END IF;
END;
$$;

INSERT INTO mart.dim_resolution_type (resolution_code, resolution_label)
VALUES
    ('chat_closed_by_agent', 'Closed by Agent'),
    ('customer_closed_chat', 'Closed by Customer'),
    ('system_closed_chat_after_inactivity', 'System Closed After Inactivity')
ON CONFLICT (resolution_code) DO UPDATE
SET resolution_label = EXCLUDED.resolution_label;

INSERT INTO mart.dim_survey_response (response_code, response_label, is_answered)
VALUES
    ('satisfied', 'Satisfied', TRUE),
    ('dissatisfied', 'Dissatisfied', TRUE),
    ('no_response', 'No Response', FALSE),
    ('skipped', 'Skipped', FALSE)
ON CONFLICT (response_code) DO UPDATE
SET
    response_label = EXCLUDED.response_label,
    is_answered = EXCLUDED.is_answered;

CREATE OR REPLACE PROCEDURE mart.refresh_star_schema()
LANGUAGE plpgsql
AS $$
BEGIN
    INSERT INTO mart.dim_date (
        date_key,
        full_date,
        day_of_week,
        day_name,
        month_number,
        month_name,
        quarter_number,
        year_number,
        is_weekend
    )
    SELECT DISTINCT
        TO_CHAR(event_timestamp::DATE, 'YYYYMMDD')::INTEGER AS date_key,
        event_timestamp::DATE AS full_date,
        EXTRACT(ISODOW FROM event_timestamp::DATE)::SMALLINT AS day_of_week,
        TO_CHAR(event_timestamp::DATE, 'FMDay') AS day_name,
        EXTRACT(MONTH FROM event_timestamp::DATE)::SMALLINT AS month_number,
        TO_CHAR(event_timestamp::DATE, 'FMMonth') AS month_name,
        EXTRACT(QUARTER FROM event_timestamp::DATE)::SMALLINT AS quarter_number,
        EXTRACT(YEAR FROM event_timestamp::DATE)::SMALLINT AS year_number,
        EXTRACT(ISODOW FROM event_timestamp::DATE) IN (6, 7) AS is_weekend
    FROM raw.raw_chat_logs
    WHERE event_type = 'chat_started'
    ON CONFLICT (date_key) DO NOTHING;

    INSERT INTO mart.dim_agent (agent_id, agent_name, support_team)
    SELECT DISTINCT
        agent_id,
        'Agent ' || agent_id AS agent_name,
        CASE MOD(agent_id, 3)
            WHEN 0 THEN 'Billing Support'
            WHEN 1 THEN 'Account Support'
            ELSE 'Technical Support'
        END AS support_team
    FROM raw.raw_chat_logs
    WHERE event_type = 'agent_assignment'
    ON CONFLICT (agent_id) DO UPDATE
    SET
        agent_name = EXCLUDED.agent_name,
        support_team = EXCLUDED.support_team;

    WITH chat_rollup AS (
        SELECT
            chat_id,
            MIN(event_timestamp) FILTER (WHERE event_type = 'chat_started') AS started_at,
            MIN(event_timestamp) FILTER (WHERE event_type = 'chat_entered_queue') AS entered_queue_at,
            MIN(event_timestamp) FILTER (WHERE event_type = 'agent_assignment') AS assigned_at,
            MIN(event_timestamp) FILTER (WHERE event_type = 'agent_responded') AS first_agent_response_at,
            MIN(event_timestamp) FILTER (
                WHERE event_type IN (
                    'chat_closed_by_agent',
                    'customer_closed_chat',
                    'system_closed_chat_after_inactivity'
                )
            ) AS closed_at,
            MAX(event_type) FILTER (
                WHERE event_type IN (
                    'chat_closed_by_agent',
                    'customer_closed_chat',
                    'system_closed_chat_after_inactivity'
                )
            ) AS resolution_code,
            MAX(agent_id) FILTER (WHERE event_type = 'agent_assignment') AS assigned_agent_id,
            MAX(ingestion_date) AS ingestion_date,
            COUNT(*) FILTER (WHERE event_type = 'agent_responded')::INTEGER AS agent_response_count,
            COUNT(*) FILTER (WHERE event_type = 'customer_responded')::INTEGER AS customer_response_count,
            BOOL_OR(event_type = 'chat_pushed_to_queue_due_inactivity') AS pushed_due_to_inactivity
        FROM raw.raw_chat_logs
        GROUP BY chat_id
        HAVING COUNT(*) FILTER (
            WHERE event_type IN (
                'chat_closed_by_agent',
                'customer_closed_chat',
                'system_closed_chat_after_inactivity'
            )
        ) = 1
    ),
    fact_source AS (
        SELECT
            rollup.chat_id,
            TO_CHAR(rollup.started_at::DATE, 'YYYYMMDD')::INTEGER AS date_key,
            agent.agent_key,
            resolution.resolution_type_key,
            survey_response.survey_response_key,
            rollup.started_at,
            rollup.entered_queue_at,
            rollup.assigned_at,
            rollup.first_agent_response_at,
            rollup.closed_at,
            rollup.ingestion_date,
            CASE
                WHEN rollup.entered_queue_at IS NULL OR rollup.assigned_at IS NULL THEN NULL
                ELSE EXTRACT(EPOCH FROM (
                    rollup.assigned_at - rollup.entered_queue_at
                ))::INTEGER
            END AS queue_wait_seconds,
            CASE
                WHEN rollup.assigned_at IS NULL OR rollup.first_agent_response_at IS NULL THEN NULL
                ELSE EXTRACT(EPOCH FROM (
                    rollup.first_agent_response_at - rollup.assigned_at
                ))::INTEGER
            END AS first_response_seconds,
            EXTRACT(EPOCH FROM (rollup.closed_at - rollup.started_at))::INTEGER AS resolution_seconds,
            rollup.agent_response_count,
            rollup.customer_response_count,
            rollup.pushed_due_to_inactivity,
            CASE
                WHEN rollup.assigned_at IS NULL OR rollup.first_agent_response_at IS NULL THEN NULL
                ELSE rollup.first_agent_response_at - rollup.assigned_at <= INTERVAL '5 minutes'
            END AS first_response_sla_met,
            rollup.closed_at - rollup.started_at <= INTERVAL '60 minutes' AS resolution_sla_met,
            CASE survey.customer_input
                WHEN 'satisfied' THEN TRUE
                WHEN 'dissatisfied' THEN FALSE
                ELSE NULL
            END AS satisfied_flag
        FROM chat_rollup rollup
        LEFT JOIN mart.dim_agent agent
          ON agent.agent_id = rollup.assigned_agent_id
        JOIN mart.dim_resolution_type resolution
          ON resolution.resolution_code = rollup.resolution_code
        JOIN raw.survey survey
          ON survey.chat_id = rollup.chat_id
        JOIN mart.dim_survey_response survey_response
          ON survey_response.response_code = CASE
              WHEN survey.survey_skipped THEN 'skipped'
              WHEN survey.customer_input IS NULL THEN 'no_response'
              ELSE survey.customer_input
          END
    ),
    deleted_stale_facts AS (
        DELETE FROM mart.fact_chat_resolution fact
        WHERE NOT EXISTS (
            SELECT 1
            FROM fact_source source
            WHERE source.chat_id = fact.chat_id
        )
        RETURNING fact.chat_id
    )
    INSERT INTO mart.fact_chat_resolution (
        chat_id,
        date_key,
        agent_key,
        resolution_type_key,
        survey_response_key,
        started_at,
        entered_queue_at,
        assigned_at,
        first_agent_response_at,
        closed_at,
        ingestion_date,
        queue_wait_seconds,
        first_response_seconds,
        resolution_seconds,
        agent_response_count,
        customer_response_count,
        pushed_due_to_inactivity,
        first_response_sla_met,
        resolution_sla_met,
        satisfied_flag
    )
    SELECT
        chat_id,
        date_key,
        agent_key,
        resolution_type_key,
        survey_response_key,
        started_at,
        entered_queue_at,
        assigned_at,
        first_agent_response_at,
        closed_at,
        ingestion_date,
        queue_wait_seconds,
        first_response_seconds,
        resolution_seconds,
        agent_response_count,
        customer_response_count,
        pushed_due_to_inactivity,
        first_response_sla_met,
        resolution_sla_met,
        satisfied_flag
    FROM fact_source
    ON CONFLICT (chat_id) DO UPDATE
    SET
        date_key = EXCLUDED.date_key,
        agent_key = EXCLUDED.agent_key,
        resolution_type_key = EXCLUDED.resolution_type_key,
        survey_response_key = EXCLUDED.survey_response_key,
        started_at = EXCLUDED.started_at,
        entered_queue_at = EXCLUDED.entered_queue_at,
        assigned_at = EXCLUDED.assigned_at,
        first_agent_response_at = EXCLUDED.first_agent_response_at,
        closed_at = EXCLUDED.closed_at,
        ingestion_date = EXCLUDED.ingestion_date,
        queue_wait_seconds = EXCLUDED.queue_wait_seconds,
        first_response_seconds = EXCLUDED.first_response_seconds,
        resolution_seconds = EXCLUDED.resolution_seconds,
        agent_response_count = EXCLUDED.agent_response_count,
        customer_response_count = EXCLUDED.customer_response_count,
        pushed_due_to_inactivity = EXCLUDED.pushed_due_to_inactivity,
        first_response_sla_met = EXCLUDED.first_response_sla_met,
        resolution_sla_met = EXCLUDED.resolution_sla_met,
        satisfied_flag = EXCLUDED.satisfied_flag;
END;
$$;
