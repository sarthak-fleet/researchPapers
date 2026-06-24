# researchPapers — PROJECT STATUS

Last updated: 2026-06-24

## Why / What

researchPapers is a ClickHouse-backed academic-paper intelligence platform. It indexes papers from arXiv, OpenReview, bioRxiv, and medRxiv, exposes FastAPI search and insight endpoints, and serves an Astro + React dashboard for semantic search, citation graph analysis, tags, reviews, hot papers, sleepers, similar papers, and HighSignal-style research digests.

**Users:** Researchers browsing/searching the corpus; demo viewers evaluating paid answer APIs over curated data; operators running ingest/overlay jobs; frontend readers of static JSON exports and live API.

**Constraints:** Runtime is ClickHouse-only for API, frontend, and pipeline reads. Warm restore from dump preferred over cold rebuild (hours). Same-host deployment preferred over CDN until launch path decided.

**IN scope:** ~488k paper corpus, FastAPI search/insights, overlay enrichment jobs, Astro dashboard, static JSON export path, Cloudflare Pages demo, paid-answer/RAG demo path, warm restore deploy script.

**OUT of scope:** Confirmed public CDN launch, legacy Postgres pipeline (except optional old CLI paths), full-corpus Semantic Scholar backfill, manual author curation at scale.

## Dependencies

### External

- **ClickHouse 24.10 (Docker Compose):** Primary store for papers, references, embeddings, clusters, overlays.
- **arXiv API:** Metadata + abstract refresh overlay.
- **OpenAlex:** Top-N CS metadata selection.
- **OpenReview:** NeurIPS/ICLR papers + peer reviews.
- **bioRxiv / medRxiv:** Preprint ingestion.
- **Semantic Scholar:** Citation enrichment → `citation_overlay_v2`.
- **sentence-transformers (MiniLM 384-d):** Embeddings for all papers.
- **MLX (Qwen2.5-3B-4bit tagging):** Premium tagging subset.
- **spaCy v2:** Noun-chunk tags.
- **Optional Postgres:** Legacy CLI paths (`ingest`, `download-pdfs`) only.
- **Cloudflare Pages:** Public Astro demo at `https://research-papers.pages.dev`.

Corpus stats: 488,491 papers · full-corpus PageRank · 64 semantic clusters · MLX + spaCy tags · correction overlays · ~1.05M paper→paper edges.

### Internal (fleet)

- **High Signal:** Insight surface patterns (sleepers, hot, similar).
- **knowledge-base:** Optional server-side Knowledgebase RAG service for cited paid-answer demos over the `research-papers` domain.

### Stack & commands

**Stack:** ClickHouse 24.10 (Docker Compose) · Python 3.11+ · FastAPI · Typer CLI · uvicorn · sentence-transformers (MiniLM 384-d) · MLX (Qwen2.5-3B-4bit tagging) · spaCy v2 · Astro 5 + React + Tailwind + shadcn/ui in `web/` · scipy sparse PageRank · NetworkX · optional Postgres for legacy CLI.

| Command | Purpose |
| --- | --- |
| `./scripts/deploy.sh /path/to/researchpapers_data_*.tar.gz` | Warm restore (preferred — minutes) |
| `docker compose up -d clickhouse` | Start ClickHouse |
| `uv sync` | Install Python deps |
| `uv run papers select-top --n 400000` | Cold rebuild steps (see DEPLOY.md) |
| `uv run papers ingest-openreview` / `ingest-biorxiv` / `backfill-references` / `refresh-metadata` / `pagerank-full` / `embed` / `cluster-embeddings` / `spacy-tag-v2` / `mlx-tag-v3 --shards 3` / `export-ch` | Cold rebuild pipeline |
| `uv run papers api-serve --host 0.0.0.0 --port 8000` | FastAPI server |
| `uv run papers warm-update` / `--build-web` | Overlay maintenance |
| `uv run papers enrich-citations` / `refresh-abstracts` / `build-author-graph` | Overlay jobs |
| `cd web && npm install && npm run dev` | Astro dev |
| `cd web && npm run build` | Frontend build |
| `uv run pytest` | Tests |

See `DEPLOY.md` for LAN/CDN deployment shapes.

**Entrypoints:** Typer CLI (`uv run papers …`) · FastAPI on `:8000` · Astro `web/` · `scripts/deploy.sh`.

## Timeline

- **Corpus build:** ~488k papers across arxiv, OpenReview, bioRxiv, medRxiv with ~1.05M paper→paper edges; full-corpus PageRank → `paper_scores_v2`; MiniLM embeddings (384-d) for all papers; 64 semantic clusters; spaCy noun-chunk tags + MLX premium tagging subset.
- **Overlay enrichment shipped:** Semantic Scholar enrichment → `citation_overlay_v2`; ArXiv abstract refresh → `abstract_overlay_v2`; author graph → `authors_v2`, `paper_authorships_v2`.
- **2026-06-24:** Cloudflare Pages demo deployed at `https://research-papers.pages.dev`; frontend no longer defaults to localhost APIs; Research Answer API panel ships a same-origin RAG proxy path. `RAG_SERVICE_KEY` is configured on Pages production and the clean `research-papers-cited1000-v2` Knowledgebase domain is seeded with 3,863 OpenAlex Computer Science papers over 999 citations, using local BGE-base embeddings uploaded through vector ingest. The bundled-data fallback remains for resilience.

## Products

| Surface | URL / port |
| --- | --- |
| Public production | `https://research-papers.pages.dev` (Cloudflare Pages) |
| Pages RAG Function | `/api/rag/query` on Pages; `RAG_SERVICE_KEY` configured for the live `research-papers-cited1000-v2` Knowledgebase path |
| FastAPI (local/deploy) | `http://0.0.0.0:8000` via `uv run papers api-serve` |
| ClickHouse HTTP | `:8123` (Docker) |
| Astro dev | `http://127.0.0.1:4321` (`cd web && npm run dev`) |
| GitHub | `https://github.com/sarthak-fleet/researchPapers` |
| Static JSON export | `web/public/data/*.json` for Astro build |

## Features (shipped)

### Architecture

- Ingest sources: arxiv, OpenAlex, OpenReview, bioRxiv/medRxiv → Typer CLI overlay/ingest jobs.
- ClickHouse 24.10 (Docker) stores papers, references, embeddings, clusters, `paper_scores_v2`, `citation_overlay_v2`, `abstract_overlay_v2`, `authors_v2`.
- FastAPI on `:8000` serves search, paper detail, semantic search, sleepers, hot papers, similar papers, tags, authors, reviews.
- Static export: `uv run papers export-ch` → JSON in `web/public/data/*.json` for Astro build.
- Astro + React dashboard in `web/` reads FastAPI and/or static JSON depending on deploy shape.
- Runtime reads are ClickHouse-only; Postgres remains optional for legacy CLI paths (`ingest`, `download-pdfs`) only.
- Overlay jobs (`warm-update`, `enrich-citations`, `refresh-abstracts`, `build-author-graph`) maintain correction layers post-deploy.

### Ingestion & corpus

- ~488k papers across arxiv, OpenReview, bioRxiv, medRxiv with ~1.05M paper→paper edges.
- Full-corpus PageRank → `paper_scores_v2`.
- MiniLM embeddings (384-d) for all papers; 64 semantic clusters.
- spaCy noun-chunk tags + MLX premium tagging subset.

### API (FastAPI)

- Health/stats, search, paper detail, semantic search, sleepers, hot papers, similar papers.
- Tags (top-rated, drilldown), authors (by-tag, by-id), reviews (top-rated OpenReview).
- Author graph v2: `/authors/v2/{id}`, `/coauthors`, `/authors/resolve`.

### Overlays & enrichment

- **Semantic Scholar enrichment** (`papers enrich-citations`) → `citation_overlay_v2`; ranking prefers S2 counts with provenance.
- **ArXiv abstract refresh** (`papers refresh-abstracts`) → `abstract_overlay_v2`; search/detail use corrected text.
- **Author graph** (`papers build-author-graph`) → `authors_v2`, `paper_authorships_v2`.

### Frontend & export

- Astro frontend wired to FastAPI/ClickHouse data path.
- Static JSON exports via `uv run papers export-ch` → `web/public/data/*.json`.
- Public Pages build uses bundled static JSON when no live API base is configured, so search/similar-paper demo flows do not point at localhost.
- Research Answer API panel calls same-origin `/api/rag/query` on Pages or FastAPI `/rag/query` in same-host mode; the live path defaults to semantic retrieval plus synthesized cited answers through Knowledgebase/free-ai. If the live Knowledgebase service is unavailable, the browser falls back to a cited answer over bundled hot papers, sleepers, OpenReview ratings, and semantic clusters.
- Warm restore, cold rebuild, deployment shapes documented.

## Todo / Planned / Deferred / Blocked

### Planned

1. Add a small golden-question regression check for the Research Answer API default prompts.
2. Keep static JSON exports fresh after ingestion/retagging: `uv run papers export-ch` + frontend rebuild.
3. Run overlay jobs on production corpus after deploy: `uv run papers warm-update`.

### Deferred

- Full same-host live API deployment remains separate from the Cloudflare Pages static demo.
- Legacy Postgres pipeline unless needed for cold restore or old commands.
- OrbStack/macOS VM instability — environment issue, not product regression without repro on stable Docker.
- Full-corpus Semantic Scholar backfill and manual author curation.
- Static JSON exports drift from ClickHouse until `export-ch` + frontend rebuild rerun.
- Overlay jobs need post-deploy runs on live corpus.
- Cold rebuild remains hours-long; warm restore from dump is the practical path.

### Blocked

- (none)
