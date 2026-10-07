-- =====================================================================
-- 005_keyword_index.sql : full-text (keyword) search column for HYBRID retrieval
-- Run as OWNER:  python -m scripts.run_sql db/005_keyword_index.sql
-- Reversible:    ALTER TABLE healthbot.hc_policy_chunks DROP COLUMN content_tsv;
-- =====================================================================

SET search_path TO healthbot, public;

-- A tsvector is Postgres's pre-processed text for keyword search: lower-cased, stop words
-- ("the", "is") removed, words reduced to stems ("authorizations" -> "author").
-- GENERATED ... STORED means Postgres keeps it in sync automatically whenever `content`
-- changes, so ingestion code never has to know this column exists.
ALTER TABLE hc_policy_chunks
    ADD COLUMN IF NOT EXISTS content_tsv tsvector
    GENERATED ALWAYS AS (to_tsvector('english', content)) STORED;

-- GIN = an inverted index (word -> list of chunks containing it), like a book's index.
CREATE INDEX IF NOT EXISTS idx_hc_chunks_tsv ON hc_policy_chunks USING gin (content_tsv);
