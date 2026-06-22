# researchPapers

Multi-source academic-paper data platform on ClickHouse.
**488k papers** across arxiv, OpenReview, bioRxiv, medRxiv — with semantic
search, citation graph PageRank, peer-review aggregations, MLX/spaCy
auto-tagging, and HighSignal-style insight surfaces (sleepers, hot now,
papers-like-this, authors-by-tag).

Stack: ClickHouse 24.10 (Dockerized) · FastAPI · Astro 5 + React + Tailwind
+ shadcn/ui · sentence-transformers · MLX (Qwen2.5-3B-4bit) · spaCy v2.

## Status

- 488,491 papers ingested, ~1.05M paper→paper edges, full-corpus PageRank
  computed, all papers embedded (all-MiniLM-L6-v2, 384-dim) and clustered
  into 64 semantic clusters.
- Runtime is **ClickHouse-only**. Postgres remains as an optional
  dependency for legacy CLI commands (e.g. `ingest`, `download-pdfs`) but
  is not required for the API, the frontend, or any current pipeline.
- The Astro frontend is fully wired to the FastAPI backend. See `DEPLOY.md`.
- GitHub: <https://github.com/sarthak-fleet/researchPapers>

## Quickstart (warm — from a dump)

If you have the `researchpapers_data_*.tar.gz` dump in hand, this is the
fastest path to a running system. Needs Docker + `uv`.

```bash
git clone https://github.com/sarthak-fleet/researchPapers
cd researchPapers
./scripts/deploy.sh /path/to/researchpapers_data_*.tar.gz
# CH on :8123, FastAPI on :8000

# Frontend (separate terminal)
cd web && npm install && npm run dev   # http://127.0.0.1:4321
```

For LAN/CDN deployments, see **[DEPLOY.md](DEPLOY.md)**.

## Quickstart (cold — rebuild from scratch)

A full rebuild takes hours. Outline:

```bash
docker compose up -d clickhouse                  # CH on :8123
uv sync                                          # python deps
uv run papers select-top --n 400000              # OpenAlex top-N CS metadata
uv run papers ingest-openreview                  # NeurIPS/ICLR + reviews
uv run papers ingest-biorxiv                     # bioRxiv + medRxiv
uv run papers backfill-references                # paper→paper edges
uv run papers refresh-metadata                   # arxiv API fixups for top papers
uv run papers pagerank-full                      # writes paper_scores_v2
uv run papers embed                              # all-MiniLM-L6-v2 (~17 min)
uv run papers cluster-embeddings                 # MiniBatchKMeans, 64 clusters
uv run papers spacy-tag-v2                       # noun-chunk tags (CPU)
uv run papers mlx-tag-v3 --shards 3              # premium subset, MLX on Apple Silicon
uv run papers export-ch                          # write web/public/data/*.json
uv run papers api-serve --host 0.0.0.0 --port 8000
```

## Architecture

```
                                   ┌──────────────────────┐
   arxiv API ──┐                   │  ClickHouse (papers) │
   OpenAlex ───┼──► ingesters ───► │  papers              │
   OpenReview ─┤                   │  paper_tags          │
   bioRxiv ────┘                   │  references_paper    │
                                   │  citation_history    │
                                   │  paper_embeddings    │
                                   │  paper_clusters      │
                                   │  paper_metadata_v2   │ ◄── overlay
                                   │  paper_scores_v2     │ ◄── overlay
                                   └──────────┬───────────┘
                                              │
                            ┌─────────────────┼─────────────────┐
                            ▼                 ▼                 ▼
                       ch_exports.py     pagerank_full.py   refresh_metadata.py
                       (JSON for FE)     (scipy.sparse)     (arxiv API title fix)
                            │                                   │
                            ▼                                   ▼
                       web/public/data/*.json            paper_metadata_v2
                            │
                            ▼
                       Astro 5 + React (web/)
                            ▲
                            │
                       FastAPI (src/researchpapers/api.py)
                       /search /papers /sleepers /hot /similar
                       /semantic-search /tags /authors /reviews
```

## API endpoints

All under the FastAPI server (`uv run papers api-serve`):

| Endpoint | What |
| --- | --- |
| `GET /healthz`, `GET /stats` | health + corpus stats |
| `GET /search?q=...` | full-text-ish search via CH `LIKE` |
| `GET /papers/{paper_id}` | canonical paper detail (joined w/ overlays) |
| `GET /semantic-search?q=...` | encodes q via MiniLM, `cosineDistance` over `paper_embeddings` |
| `GET /sleepers` | papers with late citation spikes |
| `GET /hot` | recent papers gaining attention |
| `GET /similar/{paper_id}` | nearest neighbours by embedding |
| `GET /tags/top-rated` | tag → mean rating cross-join (uses OpenReview scores) |
| `GET /tags/{tag}` | drilldown: papers under a tag |
| `GET /authors/by-tag/{tag}` | top authors per topic |
| `GET /authors/by-id/{openalex_id}` | full author profile |
| `GET /reviews/top-rated` | best-reviewed OpenReview papers |

## Using the data

Once `./scripts/deploy.sh` has the stack running (FastAPI on `:8000`, CH on
`:8123`), here is how to actually pull insights out of the corpus.

### Via the HTTP API (recommended)

```bash
# Corpus stats — confirms data shape: 488k papers across 4 sources, ~1.05M
# paper→paper edges, ~478k embedded.
curl -s http://127.0.0.1:8000/stats | jq

# Substring search across titles + authors.
curl -s "http://127.0.0.1:8000/search?q=attention+is+all+you+need&limit=5" | jq

# Canonical detail for one paper (with corrected title from paper_metadata_v2
# and PageRank from paper_scores_v2 already merged in).
curl -s http://127.0.0.1:8000/papers/arxiv:1706.03762 | jq

# Semantic search — encodes the query through MiniLM and ranks by cosine
# distance against all 478k embeddings.
curl -s "http://127.0.0.1:8000/semantic-search?q=mixture+of+experts+routing&limit=10" | jq

# "Sleepers" — papers that were quiet for years then woke up. Useful for
# finding under-cited fundamentals that suddenly mattered.
curl -s "http://127.0.0.1:8000/sleepers?limit=20" | jq

# "Hot" — recent papers gaining citations fast. The freshness signal.
curl -s "http://127.0.0.1:8000/hot?limit=20" | jq

# "Similar" — nearest neighbours by embedding for a given paper.
curl -s "http://127.0.0.1:8000/similar/arxiv:1706.03762?limit=10" | jq

# Tag → mean OpenReview rating. The "what topics get accepted at top venues"
# signal. Comes from a cross-join of paper_tags × openreview_reviews.
curl -s "http://127.0.0.1:8000/tags/top-rated?limit=20" | jq

# Drilldown: all papers under a single tag, ordered by PageRank.
curl -s "http://127.0.0.1:8000/tags/transformers?limit=20" | jq

# Author profile by OpenAlex ID (only populated for top-2000 refreshed papers).
curl -s http://127.0.0.1:8000/authors/by-id/A5024211345 | jq
```

### Via direct ClickHouse queries

The API only exposes the curated insights; for ad-hoc questions, talk to CH
directly. Connect with `docker exec -it researchpapers_ch clickhouse-client
--user papers --password papers -d papers`, or hit HTTP on `:8123`.

```sql
-- Source breakdown
SELECT source, count() FROM papers GROUP BY source ORDER BY count() DESC;
--  arxiv 399902 │ biorxiv 64829 │ openreview 30327 │ medrxiv 17332

-- Canonical view of one paper, with title/year corrections applied.
SELECT
  p.paper_id,
  effective_year(p.source, p.arxiv_id, p.submitted_date) AS year,
  p.citation_count,
  coalesce(nullIf(m.title, ''), p.title) AS title
FROM papers p
LEFT JOIN paper_metadata_v2 m USING (paper_id)
WHERE p.paper_id = 'arxiv:1706.03762';
--  arxiv:1706.03762 │ 2017 │ 6551 │ Attention Is All You Need

-- Top 10 by full-corpus PageRank.
SELECT
  s.paper_id,
  round(s.pagerank, 6) AS pr,
  coalesce(nullIf(m.title, ''), p.title) AS title
FROM paper_scores_v2 s
LEFT JOIN papers p USING (paper_id)
LEFT JOIN paper_metadata_v2 m USING (paper_id)
ORDER BY s.pagerank DESC LIMIT 10;

-- Top arxiv 2024 papers by citations (year corrected via UDF).
SELECT
  p.paper_id, p.citation_count,
  coalesce(nullIf(m.title, ''), p.title) AS title
FROM papers p LEFT JOIN paper_metadata_v2 m USING (paper_id)
WHERE p.source = 'arxiv'
  AND effective_year(p.source, p.arxiv_id, p.submitted_date) = 2024
ORDER BY p.citation_count DESC LIMIT 10;

-- Nearest neighbours of any paper, by embedding.
WITH q AS (SELECT embedding FROM paper_embeddings WHERE paper_id = 'arxiv:1706.03762' LIMIT 1)
SELECT e.paper_id, round(cosineDistance(e.embedding, (SELECT embedding FROM q)), 4) AS d,
       coalesce(nullIf(m.title, ''), p.title) AS title
FROM paper_embeddings e
LEFT JOIN papers p USING (paper_id)
LEFT JOIN paper_metadata_v2 m USING (paper_id)
WHERE e.paper_id != 'arxiv:1706.03762'
ORDER BY d ASC LIMIT 10;

-- Most common spaCy noun-chunk tags across the corpus.
SELECT arrayJoin(tags) AS tag, count() AS c
FROM paper_tags WHERE tagger = 'spacy_v2'
GROUP BY tag ORDER BY c DESC LIMIT 20;
--  language models │ machine learning │ deep learning │ LLMs │ ...

-- All papers in semantic cluster N (0..63), top-cited first.
SELECT p.paper_id, p.citation_count,
       coalesce(nullIf(m.title, ''), p.title) AS title
FROM paper_clusters c
JOIN papers p USING (paper_id)
LEFT JOIN paper_metadata_v2 m USING (paper_id)
WHERE c.cluster_id = 17
ORDER BY p.citation_count DESC LIMIT 20;
```

### Via the Astro frontend

`cd web && npm install && npm run dev` (then http://127.0.0.1:4321) is the
visual entry point. Each table is a React island bound to either a static
JSON in `web/public/data/` (built by `papers export-ch`) or a live FastAPI
endpoint (search, semantic search, similar). The `/digest` page is the
HighSignal-style summary.

### Refreshing the static JSON exports

The dashboard's tables (sleepers, hot, top-authors, communities, etc.) read
from `web/public/data/*.json`. To regenerate after new ingestion or a
re-tag run:

```bash
uv run papers export-ch         # rewrites web/public/data/*.json from CH
cd web && npm run build         # rebuild the static bundle
```

The live endpoints (search, semantic-search, similar, sleepers, hot, etc.)
always read from CH directly — no rebuild needed.

## CLI cheatsheet

**One command (16 GB M1 Pro, RAM-aware):**

```bash
docker compose up -d clickhouse
uv run papers warm-update --build-web   # overlays + exports + static build
uv run papers api-serve --lean          # API without resident ML models
```

```bash
uv run papers api-serve --lean           # default: low-RAM API (~400 MB saved)
uv run papers warm-update                # sequential overlay refresh
uv run papers export-ch                  # write JSON files for the static FE
uv run papers refresh-metadata           # pull arxiv API + OpenAlex into paper_metadata_v2
uv run papers enrich-citations           # Semantic Scholar counts → citation_overlay_v2
uv run papers refresh-abstracts          # fix contaminated arxiv abstracts → abstract_overlay_v2
uv run papers build-author-graph         # authors_v2 + paper_authorships_v2
uv run papers pagerank-full              # full-corpus PageRank → paper_scores_v2
uv run papers embed                      # all-MiniLM-L6-v2 embed → paper_embeddings
uv run papers cluster-embeddings         # MiniBatchKMeans → paper_clusters
uv run papers snapshot-citations         # append to citation_history
uv run papers spacy-tag-v2               # POS-only noun-chunk tagger (arxiv)
uv run papers spacy-tag-source --source openreview
uv run papers mlx-tag-v3 --shards 3      # grouped-prompt MLX, premium subset
uv run papers status                     # progress / row counts
```

Full list: `uv run papers --help`.

## Data correction overlays

Some primary data has known defects: OpenAlex returns *latest revision dates*
for arxiv preprints (so "Attention Is All You Need" shows 2025 instead of
2017), and a handful of arxiv IDs have cross-contaminated titles/abstracts
in OpenAlex's index. We patch around these with overlay tables and two
ClickHouse UDFs:

- **`paper_metadata_v2`** (ReplacingMergeTree) — corrected titles +
  author OpenAlex IDs pulled from the arxiv API. Populated by
  `papers refresh-metadata`. Joined in via `LEFT JOIN ... ON paper_id`
  with `COALESCE(nullIf(m.title, ''), p.title)`.
- **`citation_overlay_v2`** (ReplacingMergeTree) — Semantic Scholar
  `citationCount` for top papers. Populated by `papers enrich-citations`.
  Preferred over OpenAlex counts in hot/sleepers/search when present.
  API exposes `citation_source` provenance (`semantic_scholar` |
  `openalex_refresh` | `openalex`).
- **`abstract_overlay_v2`** (ReplacingMergeTree) — authoritative arxiv
  abstracts for contaminated records. Populated by `papers refresh-abstracts`.
  Search and paper detail use corrected text; pass `--reembed` to refresh
  semantic-search embeddings for corrected papers.
- **`authors_v2` + `paper_authorships_v2`** — canonical author identities
  (OpenAlex IDs + inferred community/cluster buckets). Built by
  `papers build-author-graph`. API: `/authors/v2/{id}`, `/coauthors`,
  `/authors/resolve?name=...`.
- **`paper_scores_v2`** (ReplacingMergeTree) — full-corpus PageRank,
  written by `papers pagerank-full`. Used because `papers.pagerank_score`
  can't be `ALTER UPDATE`d cheaply (partition key on `submitted_date`).
- **`effective_year(source, arxiv_id, submitted_date)`** — parses the
  YYMM prefix of arxiv IDs (`2410.xxxxx` → 2024) and only falls back to
  `toYear(submitted_date)` for non-arxiv sources or malformed IDs.
  Defined in `clickhouse/init/02_functions.sql` so it survives container
  restarts; `deploy.sh` re-applies it after restores.
- **`effective_date(source, arxiv_id, submitted_date)`** — same idea,
  returns a `Date` for chart axes.

## RAM efficiency (16 GB M1)

Heavy jobs stream from ClickHouse in chunks and wait for free RAM between
steps. Defaults are tuned for an M1 Pro 16 GB machine with other apps open:

| Setting | Default | Why |
| --- | --- | --- |
| API `--lean` | on | semantic search uses a one-shot encoder subprocess |
| `embed --batch-size` | 64 | was 256 |
| `spacy-tag-v2` batch | 3000 papers, max 2 workers | was 25000 / up to 8 workers |
| `cluster-embeddings` | chunked partial_fit | was load-all-478k into RAM |
| `pagerank-full` | streamed edge reads | was load-all edges at once |

Use `papers warm-update` to run overlay jobs sequentially without peaking
multiple model loads. For MLX tagging, keep `--total-shards` high and run one
shard at a time.

## Repo layout

```
src/researchpapers/
  api.py                FastAPI server (all read endpoints)
  cli.py                typer entrypoint (uv run papers ...)
  ch_db.py              ClickHouse connection helper
  ch_exports.py         CH → JSON exports for the static frontend
  exporter.py           legacy multi-source exporter (CH-only)
  refresh_metadata.py   arxiv API + OpenAlex → paper_metadata_v2
  semantic_scholar_enrichment.py  S2 citation counts → citation_overlay_v2
  arxiv_abstract_refresh.py       arxiv abstract fixups → abstract_overlay_v2
  author_graph.py       canonical authors + coauthor graph
  overlays.py           shared overlay SQL + table DDL
  ram.py                RAM waits + M1 16 GB profile
  warm_update.py        one-command overlay refresh
  encode_query.py       one-shot query encoder (CLI `papers encode-query`); API loads the encoder in-process lazily
  pagerank_full.py      scipy.sparse PageRank → paper_scores_v2
  embed.py              sentence-transformers → paper_embeddings
  cluster_embeddings.py MiniBatchKMeans → paper_clusters
  mlx_tag_v3.py         MLX grouped-prompt tagger (Apple Silicon)
  noun_tag_v2.py        spaCy v2 POS-only noun-chunk tagger
  llm_tag.py            LM Studio / Ollama / MLX HTTP tagger
  openalex.py           OpenAlex client + top-cited fetcher
  openreview_ingest.py  NeurIPS/ICLR API + reviews
  biorxiv_ingest.py     bioRxiv + medRxiv + chemRxiv
  citation_history.py   snapshots → citation_history
  highsignal_report.py  sample HighSignal-style report
  watcher.py            auto re-analytics loop
clickhouse/init/
  01_schema.sql         papers, paper_tags, references_paper, ...
  02_functions.sql      effective_year / effective_date UDFs
  03_overlays.sql       citation/abstract/author overlay tables
migrations/             legacy Postgres migrations (kept for cold restore)
scripts/
  deploy.sh             unpack dump, start CH, apply UDFs, serve API
  dump_data.sh          tar CH volume + web/public/data/ exports
  migrate_pg_to_ch.py   one-shot Postgres → ClickHouse migrator
web/
  src/pages/index.astro      dashboard with React islands
  src/pages/digest.astro     HighSignal-style digest page
  src/components/            shadcn/ui + TanStack tables + charts
  public/data/*.json         exported aggregations
  public/api-config.js       runtime API base override
DEPLOY.md                    three deployment shapes (host / LAN / CDN)
```

## Known issues / deferred

- **OpenAlex citation undercount** is mitigated for top papers via
  `papers enrich-citations` → `citation_overlay_v2`. Full-corpus S2 backfill
  remains out of scope.
- **Cross-contaminated OpenAlex abstracts** are mitigated via
  `papers refresh-abstracts` → `abstract_overlay_v2`. Run with `--reembed` after
  large refreshes to update semantic-search vectors.
- **Author disambiguation** is expanded via `papers build-author-graph` into
  `authors_v2`. Inferred buckets (community/cluster) cover high-citation papers
  without OpenAlex IDs; common surnames may still collide.
- **No Vercel/CF deploy yet.** The static FE builds clean (see
  `DEPLOY.md`) but hasn't been pushed to a CDN — the user prefers
  same-host deploy unless going public.
- **OrbStack 2.1.3 + macOS 26 instability.** Apple
  Virtualization.framework occasionally kills the OrbStack VM backend
  silently. Workaround: `~/.orbstack/bin/orb start` from the CLI
  (the GUI doesn't always re-spawn). Linux Docker daemons are fine.

## Environment

`.env` is optional. `CONTACT_EMAIL` is read by the polite-scraping headers;
`POSTGRES_URL` is only needed for the few legacy CLIs that still touch
Postgres (ingest, download-pdfs, extract-urls). See `.env.example`.
