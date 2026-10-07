-- =====================================================================
-- 007_source_categories.sql : tag every source with a CATEGORY and (for drug labels) the DRUG it describes
-- Run as OWNER:  python -m scripts.run_sql db/007_source_categories.sql
--
-- WHY: retrieval must be able to say "search ONLY the FDA label of lisinopril". That is METADATA
-- FILTERING: a cheap, exact SQL filter applied before/with the vector search. It is far more precise
-- than hoping the embedding of "lisinopril" lands near the right chunks.
--   category = 'coverage_policy' -> Medicare/insurance rules (the original 4 PDFs)
--   category = 'drug_label'      -> official FDA prescribing information (drug information mode)
-- =====================================================================

SET search_path TO healthbot, public;

ALTER TABLE hc_policy_sources
    ADD COLUMN IF NOT EXISTS category TEXT NOT NULL DEFAULT 'coverage_policy'
        CHECK (category IN ('coverage_policy', 'drug_label'));          -- existing rows get the default

ALTER TABLE hc_policy_sources
    ADD COLUMN IF NOT EXISTS drug_id INT REFERENCES hc_drugs (drug_id);  -- only set for drug labels

CREATE INDEX IF NOT EXISTS idx_hc_sources_category_drug ON hc_policy_sources (category, drug_id);
