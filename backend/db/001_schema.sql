-- =====================================================================
-- 001_schema.sql : relational tables for the healthcare/pharmacy chatbot
-- Schema : healthbot (shared with another project; we ONLY add hc_* tables)
-- Safe to re-run: every statement uses IF NOT EXISTS.
-- Run as the OWNER role:  python -m scripts.run_sql db/001_schema.sql
-- ALL DATA IN THIS APP IS SYNTHETIC. No real patient information.
-- =====================================================================

SET search_path TO healthbot, public;

-- ---------------------------------------------------------------------
-- Insurance plans: one row per plan a patient can be enrolled in.
-- ---------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS hc_insurance_plans (
    plan_id            SERIAL PRIMARY KEY,            -- auto-incrementing id
    plan_name          TEXT NOT NULL UNIQUE,
    carrier            TEXT NOT NULL,                 -- fictional insurer name
    plan_type          TEXT NOT NULL
                       CHECK (plan_type IN ('HMO','PPO','EPO','Medicare Part D')),
    monthly_premium    NUMERIC(8,2) NOT NULL CHECK (monthly_premium >= 0),
    annual_deductible  NUMERIC(8,2) NOT NULL CHECK (annual_deductible >= 0),
    out_of_pocket_max  NUMERIC(8,2) NOT NULL CHECK (out_of_pocket_max >= 0)
);

-- ---------------------------------------------------------------------
-- Drugs: a small catalog of common medications.
-- ---------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS hc_drugs (
    drug_id       SERIAL PRIMARY KEY,
    generic_name  TEXT NOT NULL UNIQUE,
    brand_name    TEXT,                               -- NULL if generic only
    drug_class    TEXT NOT NULL                       -- e.g. 'Statin'
);

-- ---------------------------------------------------------------------
-- Coverage: what a plan charges for a drug (join table, composite key).
-- tier 1 = cheapest generics ... tier 5 = specialty.
-- ---------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS hc_plan_drug_coverage (
    plan_id              INT NOT NULL REFERENCES hc_insurance_plans(plan_id) ON DELETE CASCADE,
    drug_id              INT NOT NULL REFERENCES hc_drugs(drug_id)           ON DELETE CASCADE,
    tier                 SMALLINT NOT NULL CHECK (tier BETWEEN 1 AND 5),
    copay                NUMERIC(8,2) NOT NULL CHECK (copay >= 0),
    requires_prior_auth  BOOLEAN NOT NULL DEFAULT FALSE,
    quantity_limit       TEXT,                        -- e.g. '30 tablets / 30 days'
    PRIMARY KEY (plan_id, drug_id)                    -- one row per (plan, drug)
);

-- ---------------------------------------------------------------------
-- Patients: SYNTHETIC people only.
-- ---------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS hc_patients (
    patient_id     SERIAL PRIMARY KEY,
    first_name     TEXT NOT NULL,
    last_name      TEXT NOT NULL,
    date_of_birth  DATE NOT NULL,
    sex            TEXT NOT NULL CHECK (sex IN ('F','M','X')),
    phone          TEXT,
    member_id      TEXT NOT NULL UNIQUE,              -- insurance member number (fake)
    plan_id        INT  NOT NULL REFERENCES hc_insurance_plans(plan_id),
    allergies      TEXT[] NOT NULL DEFAULT '{}'       -- Postgres array type
);

-- ---------------------------------------------------------------------
-- Prescriptions: which patient takes which drug.
-- ---------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS hc_prescriptions (
    prescription_id    SERIAL PRIMARY KEY,
    patient_id         INT NOT NULL REFERENCES hc_patients(patient_id) ON DELETE CASCADE,
    drug_id            INT NOT NULL REFERENCES hc_drugs(drug_id),
    dosage             TEXT NOT NULL,                 -- e.g. '20 mg'
    frequency          TEXT NOT NULL,                 -- e.g. 'once daily'
    quantity           INT  NOT NULL CHECK (quantity > 0),
    refills_remaining  INT  NOT NULL DEFAULT 0 CHECK (refills_remaining >= 0),
    prescriber_name    TEXT NOT NULL,                 -- fictional
    status             TEXT NOT NULL DEFAULT 'active'
                       CHECK (status IN ('active','completed','discontinued')),
    start_date         DATE NOT NULL,
    end_date           DATE,
    CHECK (end_date IS NULL OR end_date >= start_date)
);

-- Indexes on foreign keys: Postgres does NOT create these automatically,
-- and our MCP tools will constantly look up "prescriptions for patient X".
CREATE INDEX IF NOT EXISTS idx_hc_rx_patient   ON hc_prescriptions(patient_id);
CREATE INDEX IF NOT EXISTS idx_hc_rx_status    ON hc_prescriptions(patient_id, status);
CREATE INDEX IF NOT EXISTS idx_hc_patients_plan ON hc_patients(plan_id);

-- ---------------------------------------------------------------------
-- Least privilege: the chatbot's role may only READ our tables.
-- Written inside DO so the script still runs if the role is named differently.
-- ---------------------------------------------------------------------
DO $$
BEGIN
    IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'healthbot_app') THEN
        GRANT USAGE ON SCHEMA healthbot TO healthbot_app;
        GRANT SELECT ON hc_insurance_plans, hc_drugs, hc_plan_drug_coverage,
                        hc_patients, hc_prescriptions TO healthbot_app;
    END IF;
END $$;
