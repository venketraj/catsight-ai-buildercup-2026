-- One row per analysis, newest first, with its Courtroom outcome joined on.
-- Log Analytics (SQL) over the _Default bucket; used by the dashboard's run
-- table (scripts/observability_dashboard.json). Columns come from the
-- analysis_done and courtroom_* lines written by backend/app/logs.py and main.py.
WITH runs AS (
  SELECT
    timestamp,
    JSON_VALUE(json_payload, '$.run_id')                                   AS run_id,
    JSON_VALUE(json_payload, '$.event_id')                                 AS event,
    JSON_VALUE(json_payload, '$.mode')                                     AS mode,
    SAFE_CAST(JSON_VALUE(json_payload, '$.money_seconds') AS FLOAT64)      AS money_s,
    SAFE_CAST(JSON_VALUE(json_payload, '$.seconds') AS FLOAT64)            AS total_s,
    SAFE_CAST(JSON_VALUE(json_payload, '$.agent_seconds.exposure_analyst') AS FLOAT64) AS exposure_s,
    SAFE_CAST(JSON_VALUE(json_payload, '$.agent_seconds.wording_checker') AS FLOAT64)  AS wording_s,
    SAFE_CAST(JSON_VALUE(json_payload, '$.agent_seconds.verifier') AS FLOAT64)         AS verifier_s,
    SAFE_CAST(JSON_VALUE(json_payload, '$.agent_seconds.reporter') AS FLOAT64)         AS reporter_s,
    SAFE_CAST(JSON_VALUE(json_payload, '$.calls') AS INT64)                AS model_calls,
    SAFE_CAST(JSON_VALUE(json_payload, '$.tool_calls') AS INT64)           AS tool_calls,
    SAFE_CAST(JSON_VALUE(json_payload, '$.retrievals') AS INT64)           AS retrievals,
    SAFE_CAST(JSON_VALUE(json_payload, '$.tokens_in') AS INT64)            AS tokens_in,
    SAFE_CAST(JSON_VALUE(json_payload, '$.tokens_out') AS INT64)           AS tokens_out,
    SAFE_CAST(JSON_VALUE(json_payload, '$.cost_usd') AS FLOAT64)           AS cost_usd,
    SAFE_CAST(JSON_VALUE(json_payload, '$.verified') AS INT64)             AS flags_verified,
    SAFE_CAST(JSON_VALUE(json_payload, '$.withheld') AS INT64)             AS flags_withheld
  FROM `techno-crackers-catsight.global._Default._AllLogs`
  WHERE JSON_VALUE(json_payload, '$.component') = 'catsight-api'
    AND JSON_VALUE(json_payload, '$.event') = 'analysis_done'
),
court AS (
  SELECT
    JSON_VALUE(json_payload, '$.run_id') AS run_id,
    ANY_VALUE(CASE JSON_VALUE(json_payload, '$.event')
      WHEN 'courtroom_done' THEN CONCAT('argued, ', JSON_VALUE(json_payload, '$.sides_verified'), ' of 2 sides verified')
      ELSE 'skipped' END) AS courtroom,
    SUM(SAFE_CAST(JSON_VALUE(json_payload, '$.cost_usd') AS FLOAT64)) AS courtroom_cost_usd
  FROM `techno-crackers-catsight.global._Default._AllLogs`
  WHERE JSON_VALUE(json_payload, '$.component') = 'catsight-api'
    AND JSON_VALUE(json_payload, '$.event') IN ('courtroom_done', 'courtroom_skipped')
  GROUP BY run_id
)
SELECT
  FORMAT_TIMESTAMP('%d %b %H:%M', r.timestamp, 'Asia/Kolkata') AS time_ist,
  r.event, r.mode, r.money_s, r.total_s,
  r.exposure_s, r.wording_s, r.verifier_s, r.reporter_s,
  r.model_calls, r.tool_calls, r.retrievals, r.tokens_in, r.tokens_out,
  r.cost_usd, r.flags_verified, r.flags_withheld,
  IFNULL(c.courtroom, '-') AS courtroom, c.courtroom_cost_usd,
  r.run_id
FROM runs r LEFT JOIN court c USING (run_id)
ORDER BY r.timestamp DESC
LIMIT 50
