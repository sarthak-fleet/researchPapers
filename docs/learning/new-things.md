# New things to learn — researchPapers

Gotcha-focused stubs for novel tech encountered in this project. Concepts already linked in [external-references.md](external-references.md) are not re-explained here.

---

## ClickHouse MergeTree — ORDER BY and mutation cost

- What: MergeTree's `ORDER BY` is the physical sort key; `ALTER TABLE … UPDATE` rewrites every affected part within each partition.
- Why here: TBD
- Gotcha (from code): `papers` is `PARTITION BY toYear(...)` (`clickhouse/init/01_schema.sql:43`), so in-place mutations scan every year-partition — that's why PageRank scores live in a separate `paper_scores_v2` ReplacingMergeTree overlay instead of updating the base table (`pagerank_full.py:103-119`). README lines 301-302 document the reasoning explicitly.
- Source: See [external-references.md](external-references.md) → ClickHouse MergeTree family

---

## ClickHouse ReplacingMergeTree — FINAL is not optional

- What: ReplacingMergeTree deduplicates on background merge; without `FINAL` old and new versions of a row are both returned until the merge runs.
- Why here: TBD
- Gotcha (from code): Forgetting `FINAL` caused inflated counts and duplicate rows in production — fixed in the `fix query drift` commit (2026-06-12). Every overlay read in `api.py` and `pagerank_full.py` now uses `FINAL` or an anti-join against `paper_tags FINAL` (`noun_tag_v2.py:91-103`, `mlx_tag_v3.py:186-192`).
- Source: See [external-references.md](external-references.md) → ClickHouse MergeTree family

---

## sentence-transformers — inline storage in ClickHouse without a vector DB

- What: 384-dim L2-normalised vectors from all-MiniLM-L6-v2 stored as `Array(Float32)` per row; cosine search is a full scan via `cosineDistance`.
- Why here: TBD
- Gotcha (from code): A `vector_similarity` (HNSW, cosine) index was added to `paper_embeddings` in `clickhouse/init/01_schema.sql` (experimental in ClickHouse 24.10, GA in 25.8 — requires `allow_experimental_vector_similarity_index = 1`). The query optimizer only uses it when the SELECT distance function matches (`cosineDistance`) and LIMIT ≤ `max_limit_for_vector_search_queries` (default 100). Existing deployments apply `clickhouse/init/04_indexes.sql` + `MATERIALIZE INDEX`.
- Source: See [external-references.md](external-references.md) → sentence-transformers / Cosine distance in ClickHouse

---

## MLX / mlx-lm — JSON schema enforcement over HTTP

- What: MLX framework for running quantised LLMs on Apple Silicon unified memory; `mlx-lm` wraps it with `load()` / `generate()`.
- Why here: TBD
- Gotcha (from code): The MLX HTTP server silently ignores `response_format: json_schema` with `strict: true`; the `_make_tag_fn` for the MLX backend hard-codes `strict_schema=False` and falls back to `json_object` mode (`llm_tag.py:213-217`). The comment on line 214 reads: "MLX server does not honor strict json_schema; use json_object mode." LM Studio and direct `mlx_lm.generate` (used in `mlx_tag_v3.py`) do not have this problem.
- Source: See [external-references.md](external-references.md) → MLX / mlx-lm

---

## MLX grouped prompting — N papers per LLM call

- What: Packing multiple inputs into a single chat prompt to amortise model-load and forward-pass overhead; parse a JSON array response and fan out results.
- Why here: TBD
- Gotcha (from code): `mlx_tag_v3.py` batches 4 papers per call (`GROUP_SIZE = 4`, line 67), building a numbered prompt and regex-extracting the JSON array (`_parse_group_response`, lines 97-130). Skip rate is higher with the 1.5B model vs 3B (`SMALLER_MODEL` comment, line 66: "30% faster but 3× skip rate"). Work is flushed every 50 groups so a killed run loses at most one batch (`mlx_tag_v3.py:243-245`).
- Source: See [external-references.md](external-references.md) → MLX / mlx-lm

---

## spaCy — disabling the parser for throughput

- What: spaCy's dependency parser accounts for ~60-70% of CPU time; disabling it gives 3-5× throughput for POS-only noun-phrase extraction.
- Why here: TBD
- Gotcha (from code): `noun_tag_v2.py:120` loads the model with `disable=["parser", "ner", "lemmatizer"]`; the docstring (lines 1-13) explains the 3-5× speedup claim. The custom `_candidates_pos_only` function (lines 38-84) replaces spaCy's built-in `.noun_chunks` so that no parsed structure is needed at all.
- Source: See [external-references.md](external-references.md) → spaCy

---

## KeyBERT — evaluated but not in production pipeline

- What: Keyword extraction using sentence-transformer cosine similarity with MMR diversity.
- Why here: TBD
- Gotcha (from code): `keybert_tag.py` writes exclusively to Postgres (`UPDATE papers SET keybert_tags_json = %s`, lines 72-78) and never imports `ch_db` — it is a dead branch that was never ported to the ClickHouse `paper_tags` write path despite `keybert>=0.9.0` remaining in `pyproject.toml:15`.
- Source: See [external-references.md](external-references.md) → KeyBERT

---

## PageRank — two implementations, different scopes

- What: Power-iteration PageRank on a sparse citation graph; dangling-node mass must be redistributed explicitly or rank leaks.
- Why here: TBD
- Gotcha (from code): Two live implementations co-exist. `graph.py:104` uses `nx.pagerank()` on a Postgres-loaded within-corpus subgraph and writes back via `UPDATE papers SET pagerank_score = %s` (line 117) — legacy, not called by current CLI. `pagerank_full.py:74-98` builds a `scipy.sparse` CSR transition matrix from 1M+ ClickHouse edges, redistributes dangling-node mass explicitly (line 89: `pr[dangling].sum()`), and writes to `paper_scores_v2` (lines 103-119). bioRxiv/medRxiv papers lacking OpenAlex IDs are excluded from the full-corpus graph (`pagerank_full.py:28-30`: `WHERE length(openalex_id) > 0`) and score as 0.
- Source: See [external-references.md](external-references.md) → Original PageRank paper / scipy.sparse / NetworkX

---

## Astro + React islands — static JSON export pattern

- What: Astro's partial hydration (islands) keeps JS bundle small; data-heavy tables are hydrated from pre-built `public/data/*.json` rather than live API calls.
- Why here: TBD
- Gotcha (from code): Static exports must be regenerated (`papers export-ch` + `npm run build`) after every ingestion or re-tag run — the dashboard does not auto-refresh. Live endpoints (search, semantic-search, similar) bypass the static files and always read from ClickHouse directly (documented in README "Refreshing the static JSON exports" section).
- Source: https://docs.astro.build/en/concepts/islands/
