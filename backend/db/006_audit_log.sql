-- =====================================================================
-- 006_audit_log.sql : append-only audit trail (who did what, to whose records)
-- Run as OWNER:  python -m scripts.run_sql db/006_audit_log.sql
--
-- PRIVACY BY DESIGN: we store the LENGTH and a short HASH of each question, never the text.
-- (Questions can contain health details; a hash still lets us spot repeated attack strings.)
--
-- APPEND-ONLY: the app role gets INSERT and SELECT, but never UPDATE or DELETE, so a
-- compromised app cannot rewrite history.
-- =====================================================================

SET search_path TO healthbot, public;

CREATE TABLE IF NOT EXISTS hc_audit_log (
    audit_id           BIGSERIAL PRIMARY KEY,
    occurred_at        TIMESTAMPTZ NOT NULL DEFAULT now(),
    event_type         TEXT NOT NULL CHECK (event_type IN
                       ('login','logout','chat_turn','select_patient','list_patients','admin_view')),
    actor_role         TEXT NOT NULL CHECK (actor_role IN ('guest','patient','pharmacist','admin')),
    actor_label        TEXT NOT NULL,                 -- display name of the demo persona
    subject_member_id  TEXT,                          -- whose records were in scope (if any)
    outcome_kind       TEXT,                          -- answer | no_info | blocked | injection | ...
    guard_reason       TEXT,                          -- why the output guard blocked a draft
    intent             TEXT,                          -- the gate's classification
    tools              TEXT[] NOT NULL DEFAULT '{}',  -- MCP tools that ran
    question_len       INT,
    question_sha8      TEXT                           -- first 8 hex chars of SHA-256
);

CREATE INDEX IF NOT EXISTS idx_hc_audit_time    ON hc_audit_log (occurred_at DESC);
CREATE INDEX IF NOT EXISTS idx_hc_audit_subject ON hc_audit_log (subject_member_id, occurred_at DESC);

DO $$
BEGIN
    IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'healthbot_app') THEN
        GRANT USAGE ON SCHEMA healthbot TO healthbot_app;
        GRANT SELECT, INSERT ON hc_audit_log TO healthbot_app;        -- no UPDATE / DELETE
        GRANT USAGE, SELECT ON SEQUENCE hc_audit_log_audit_id_seq TO healthbot_app;
    END IF;
END $$;
