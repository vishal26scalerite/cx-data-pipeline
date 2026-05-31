CREATE SCHEMA IF NOT EXISTS raw;

CREATE TABLE IF NOT EXISTS raw.raw_chat_logs (
    event_id TEXT PRIMARY KEY,
    chat_id TEXT NOT NULL,
    agent_id INTEGER,
    event_type TEXT NOT NULL,
    event_timestamp TIMESTAMP NOT NULL,
    ingestion_date DATE NOT NULL,
    CONSTRAINT raw_chat_logs_event_type_ck CHECK (
        event_type IN (
            'chat_started',
            'chat_entered_queue',
            'agent_assignment',
            'agent_responded',
            'customer_responded',
            'chat_closed_by_agent',
            'customer_closed_chat',
            'chat_pushed_to_queue_due_inactivity',
            'system_closed_chat_after_inactivity'
        )
    ),
    CONSTRAINT raw_chat_logs_agent_id_ck CHECK (
        (event_type IN (
            'chat_started',
            'chat_entered_queue',
            'customer_responded',
            'customer_closed_chat',
            'system_closed_chat_after_inactivity'
        ) AND agent_id IS NULL)
        OR
        (event_type IN (
            'agent_assignment',
            'agent_responded',
            'chat_closed_by_agent',
            'chat_pushed_to_queue_due_inactivity'
        ) AND agent_id IS NOT NULL)
    )
);

ALTER TABLE raw.raw_chat_logs
    DROP CONSTRAINT IF EXISTS raw_chat_logs_event_type_ck;
ALTER TABLE raw.raw_chat_logs
    ADD CONSTRAINT raw_chat_logs_event_type_ck CHECK (
        event_type IN (
            'chat_started',
            'chat_entered_queue',
            'agent_assignment',
            'agent_responded',
            'customer_responded',
            'chat_closed_by_agent',
            'customer_closed_chat',
            'chat_pushed_to_queue_due_inactivity',
            'system_closed_chat_after_inactivity'
        )
    );

ALTER TABLE raw.raw_chat_logs
    DROP CONSTRAINT IF EXISTS raw_chat_logs_agent_id_ck;
ALTER TABLE raw.raw_chat_logs
    ADD CONSTRAINT raw_chat_logs_agent_id_ck CHECK (
        (event_type IN (
            'chat_started',
            'chat_entered_queue',
            'customer_responded',
            'customer_closed_chat',
            'system_closed_chat_after_inactivity'
        ) AND agent_id IS NULL)
        OR
        (event_type IN (
            'agent_assignment',
            'agent_responded',
            'chat_closed_by_agent',
            'chat_pushed_to_queue_due_inactivity'
        ) AND agent_id IS NOT NULL)
    );

CREATE INDEX IF NOT EXISTS raw_chat_logs_chat_time_idx
    ON raw.raw_chat_logs (chat_id, event_timestamp);
CREATE INDEX IF NOT EXISTS raw_chat_logs_ingestion_date_idx
    ON raw.raw_chat_logs (ingestion_date);

CREATE TABLE IF NOT EXISTS raw.survey (
    survey_id TEXT PRIMARY KEY,
    chat_id TEXT NOT NULL UNIQUE,
    survey_skipped BOOLEAN NOT NULL,
    customer_input TEXT,
    CONSTRAINT survey_customer_input_ck CHECK (
        customer_input IN ('satisfied', 'dissatisfied') OR customer_input IS NULL
    ),
    CONSTRAINT survey_skipped_input_ck CHECK (
        NOT survey_skipped OR customer_input IS NULL
    )
);

CREATE TABLE IF NOT EXISTS raw.batch_run_log (
    batch_id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    source_date DATE NOT NULL,
    source_chat_count INTEGER NOT NULL,
    source_event_count INTEGER NOT NULL,
    loaded_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE OR REPLACE PROCEDURE raw.validate_source_data()
LANGUAGE plpgsql
AS $$
DECLARE
    invalid_chat_id TEXT;
BEGIN
    SELECT chat_id
    INTO invalid_chat_id
    FROM raw.raw_chat_logs
    GROUP BY chat_id
    HAVING COUNT(*) FILTER (WHERE event_type = 'chat_started') <> 1
    LIMIT 1;
    IF invalid_chat_id IS NOT NULL THEN
        RAISE EXCEPTION 'Chat % must contain exactly one chat_started event.', invalid_chat_id;
    END IF;

    SELECT chat_id
    INTO invalid_chat_id
    FROM (
        SELECT
            chat_id,
            event_type,
            ROW_NUMBER() OVER (PARTITION BY chat_id ORDER BY event_timestamp, event_id) AS event_number
        FROM raw.raw_chat_logs
    ) sequenced
    WHERE event_number = 1 AND event_type <> 'chat_started'
    LIMIT 1;
    IF invalid_chat_id IS NOT NULL THEN
        RAISE EXCEPTION 'Chat % does not start with chat_started.', invalid_chat_id;
    END IF;

    SELECT chat_id
    INTO invalid_chat_id
    FROM (
        SELECT
            chat_id,
            event_timestamp,
            LAG(event_timestamp) OVER (
                PARTITION BY chat_id ORDER BY event_timestamp, event_id
            ) AS previous_timestamp
        FROM raw.raw_chat_logs
    ) sequenced
    WHERE previous_timestamp IS NOT NULL AND event_timestamp <= previous_timestamp
    LIMIT 1;
    IF invalid_chat_id IS NOT NULL THEN
        RAISE EXCEPTION 'Chat % does not have strictly increasing timestamps.', invalid_chat_id;
    END IF;

    SELECT chat_id
    INTO invalid_chat_id
    FROM raw.raw_chat_logs
    GROUP BY chat_id
    HAVING COUNT(*) FILTER (WHERE event_type = 'agent_assignment') > 1
    LIMIT 1;
    IF invalid_chat_id IS NOT NULL THEN
        RAISE EXCEPTION 'Chat % contains an agent reassignment.', invalid_chat_id;
    END IF;

    SELECT chat_id
    INTO invalid_chat_id
    FROM raw.raw_chat_logs
    GROUP BY chat_id
    HAVING COUNT(DISTINCT agent_id) FILTER (WHERE agent_id IS NOT NULL) > 1
    LIMIT 1;
    IF invalid_chat_id IS NOT NULL THEN
        RAISE EXCEPTION 'Chat % contains more than one agent_id.', invalid_chat_id;
    END IF;

    SELECT event.chat_id
    INTO invalid_chat_id
    FROM raw.raw_chat_logs event
    WHERE event.event_type IN (
            'agent_responded',
            'chat_closed_by_agent',
            'chat_pushed_to_queue_due_inactivity'
        )
      AND NOT EXISTS (
          SELECT 1
          FROM raw.raw_chat_logs assignment
          WHERE assignment.chat_id = event.chat_id
            AND assignment.event_type = 'agent_assignment'
            AND assignment.agent_id = event.agent_id
            AND assignment.event_timestamp < event.event_timestamp
      )
    LIMIT 1;
    IF invalid_chat_id IS NOT NULL THEN
        RAISE EXCEPTION 'Chat % contains agent activity without its preceding assignment.', invalid_chat_id;
    END IF;

    SELECT closure.chat_id
    INTO invalid_chat_id
    FROM raw.raw_chat_logs closure
    WHERE closure.event_type = 'system_closed_chat_after_inactivity'
      AND NOT EXISTS (
          SELECT 1
          FROM raw.raw_chat_logs pushed
          WHERE pushed.chat_id = closure.chat_id
            AND pushed.event_type = 'chat_pushed_to_queue_due_inactivity'
            AND pushed.event_timestamp = closure.event_timestamp - INTERVAL '1 hour'
      )
    LIMIT 1;
    IF invalid_chat_id IS NOT NULL THEN
        RAISE EXCEPTION 'Chat % system closure is not exactly one hour after inactivity push.', invalid_chat_id;
    END IF;

    SELECT chat_id
    INTO invalid_chat_id
    FROM raw.raw_chat_logs
    GROUP BY chat_id
    HAVING COUNT(*) FILTER (
        WHERE event_type IN (
            'chat_closed_by_agent',
            'customer_closed_chat',
            'system_closed_chat_after_inactivity'
        )
    ) > 1
    LIMIT 1;
    IF invalid_chat_id IS NOT NULL THEN
        RAISE EXCEPTION 'Chat % contains more than one closure event.', invalid_chat_id;
    END IF;

    SELECT event.chat_id
    INTO invalid_chat_id
    FROM raw.raw_chat_logs event
    JOIN (
        SELECT
            chat_id,
            MIN(event_timestamp) AS closed_at
        FROM raw.raw_chat_logs
        WHERE event_type IN (
            'chat_closed_by_agent',
            'customer_closed_chat',
            'system_closed_chat_after_inactivity'
        )
        GROUP BY chat_id
    ) closure ON closure.chat_id = event.chat_id
    WHERE event.event_timestamp > closure.closed_at
    LIMIT 1;
    IF invalid_chat_id IS NOT NULL THEN
        RAISE EXCEPTION 'Chat % contains events after closure.', invalid_chat_id;
    END IF;

    SELECT chat_id
    INTO invalid_chat_id
    FROM (
        SELECT closure.chat_id
        FROM (
            SELECT DISTINCT chat_id
            FROM raw.raw_chat_logs
            WHERE event_type IN (
                'chat_closed_by_agent',
                'customer_closed_chat',
                'system_closed_chat_after_inactivity'
            )
        ) closure
        LEFT JOIN raw.survey survey ON survey.chat_id = closure.chat_id
        WHERE survey.chat_id IS NULL

        UNION ALL

        SELECT survey.chat_id
        FROM raw.survey survey
        LEFT JOIN raw.raw_chat_logs closure
          ON closure.chat_id = survey.chat_id
         AND closure.event_type IN (
             'chat_closed_by_agent',
             'customer_closed_chat',
             'system_closed_chat_after_inactivity'
         )
        WHERE closure.chat_id IS NULL
    ) unmatched_surveys
    LIMIT 1;
    IF invalid_chat_id IS NOT NULL THEN
        RAISE EXCEPTION 'Chat % does not have a one-to-one closed-chat survey relationship.', invalid_chat_id;
    END IF;
END;
$$;
