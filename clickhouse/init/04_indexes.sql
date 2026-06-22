-- Idempotent index additions for EXISTING deployments whose tables were
-- created before these indexes existed. Fresh deploys get the indexes inline
-- in 01_schema.sql; this file is safe to re-run (IF NOT EXISTS).
--
-- Run manually against an already-populated ClickHouse, e.g.:
--   clickhouse-client --queries-file clickhouse/init/04_indexes.sql
-- (the docker-entrypoint-initdb.d scripts only run on an empty data volume).

-- Secondary indexes on `papers` for common analytical filters.
ALTER TABLE papers ADD INDEX IF NOT EXISTS idx_citation citation_count TYPE minmax GRANULARITY 1;
ALTER TABLE papers ADD INDEX IF NOT EXISTS idx_date submitted_date TYPE minmax GRANULARITY 1;

-- Venue filter on openreview reviews.
ALTER TABLE openreview_reviews ADD INDEX IF NOT EXISTS idx_venue venue TYPE set(100) GRANULARITY 1;

-- Vector similarity (ANN) index on paper_embeddings for semantic search.
-- EXPERIMENTAL in ClickHouse 24.10 (GA in 25.8); requires the setting below.
-- MATERIALIZE the index afterwards so existing parts get indexed:
--   ALTER TABLE paper_embeddings MATERIALIZE INDEX vec_idx;
ALTER TABLE paper_embeddings
    ADD INDEX IF NOT EXISTS vec_idx embedding
    TYPE vector_similarity('hnsw', 'cosineDistance', 384) GRANULARITY 1;
