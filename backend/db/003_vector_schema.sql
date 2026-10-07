-- =====================================================================
-- 003_vector_schema.sql : tables for RAG (semantic search over policy PDFs)
-- Schema : healthbot. Only hc_* tables are created; existing ones untouched.
-- Run as OWNER:  python -m scripts.run_sql db/003_vector_schema.sql
--
-- EMBEDDING SIZE = 768, matching the local model BAAI/bge-base-en-v1.5.
-- A vector column's size is fixed. Switching to a different embedding model
-- later means a NEW column/table and re-embedding every chunk.
-- =====================================================================

SET search_path TO healthbot, public;
CREATE EXTENSION IF NOT EXISTS vector;   -- already installed; no-op

-- ---------------------------------------------------------------------
-- Source registry: one row per PDF. This is what we cite in answers.
-- ---------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS hc_policy_sources (
    source_id     SERIAL PRIMARY KEY,
    title         TEXT NOT NULL,
    publisher     TEXT NOT NULL,                  -- e.g. 'CMS'
    url           TEXT NOT NULL UNIQUE,           -- link shown to the user as a citation
    doc_type      TEXT NOT NULL,                  -- 'formulary_rules', 'cost_sharing', ...
    description   TEXT,
    verified_on   DATE,                           -- last date we confirmed the URL works
    ingested_at   TIMESTAMPTZ,                    -- NULL until the ingestion pipeline runs
    content_sha256 TEXT                           -- hash of the downloaded PDF: detects changes
);

-- ---------------------------------------------------------------------
-- Chunks: pieces of each PDF + their embedding vector.
-- ---------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS hc_policy_chunks (
    chunk_id     BIGSERIAL PRIMARY KEY,
    source_id    INT NOT NULL REFERENCES hc_policy_sources(source_id) ON DELETE CASCADE,
    chunk_index  INT NOT NULL,                    -- order within the document
    page_number  INT,                             -- for "see page N" citations
    content      TEXT NOT NULL,
    embedding    vector(768) NOT NULL,
    UNIQUE (source_id, chunk_index)               -- re-ingesting can't duplicate chunks
);

-- ---------------------------------------------------------------------
-- HNSW index = fast APPROXIMATE nearest-neighbour search.
-- vector_cosine_ops makes it serve queries using the cosine-distance
-- operator <=>.  Without an index, Postgres compares against every row.
-- ---------------------------------------------------------------------
CREATE INDEX IF NOT EXISTS idx_hc_chunks_embedding
    ON hc_policy_chunks USING hnsw (embedding vector_cosine_ops);

CREATE INDEX IF NOT EXISTS idx_hc_chunks_source ON hc_policy_chunks(source_id);

-- Read-only role gets SELECT only. Ingestion (owner) does the writing.
DO $$
BEGIN
    IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'healthbot_app') THEN
        GRANT USAGE ON SCHEMA healthbot TO healthbot_app;
        GRANT SELECT ON hc_policy_sources, hc_policy_chunks TO healthbot_app;
    END IF;
END $$;
