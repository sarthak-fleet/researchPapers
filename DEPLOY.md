# Deployment

Three supported deployments. Backend stays the same (CH + FastAPI on the host);
frontend can sit alongside or on a CDN.

## 1. Backend on another machine

On the **source** machine (your dev box):
```bash
./scripts/dump_data.sh                     # creates researchpapers_data_<ts>.tar.gz
scp researchpapers_data_*.tar.gz user@target:/tmp/
```

On the **target** machine (Linux or Mac, needs Docker + uv):
```bash
git clone https://github.com/sarthak-fleet/researchPapers
cd researchPapers
./scripts/deploy.sh /tmp/researchpapers_data_*.tar.gz
# bind to LAN if you'll hit it from another box:
API_HOST=0.0.0.0 ./scripts/deploy.sh /tmp/researchpapers_data_*.tar.gz
```

Dump size is roughly the on-disk CH size (~700 MB compressed for 488k papers).

## 2. Frontend on the same machine as the backend (simplest)

After `deploy.sh` is running, in another terminal:
```bash
cd web
npm install
npm run build && npm run preview      # serves dist/ on :4321
# or for HMR dev:  npm run dev
```

The Astro app defaults to `http://127.0.0.1:8000` for the API. If the API is on
the same machine but a different port/host, edit `web/public/api-config.js`:
```js
window.__API_BASE__ = "http://192.168.1.42:8000";
```
Reload the page — no rebuild needed.

## 3. Frontend on Cloudflare Pages or Vercel

Build Astro with the API URL baked in:
```bash
cd web
PUBLIC_API_URL=https://api.your-host.com npm run build
# upload dist/ to Cloudflare Pages, Vercel, Netlify, S3, ...
```

Cloudflare Pages config:
- Build command: `npm run build`
- Output directory: `dist`
- Env var: `PUBLIC_API_URL=https://your-backend-url`

For the public RAG demo on Cloudflare Pages, leave `PUBLIC_API_URL` unset if
you want the browser to call the same-origin Pages Function at
`/api/rag/query`. The Pages Function returns a cited bundled-data answer if the
Knowledgebase secret is absent, so the demo remains usable. Configure these
Pages runtime variables/secrets when you want the full Knowledgebase RAG path:

```bash
RAG_SERVICE_URL=https://knowledgebase.sarthakagrawal927.workers.dev
RAG_DOMAIN=research-papers-cited1000-v2
RAG_SERVICE_KEY=<set as a Pages secret/runtime variable, never commit it>
```

Seed the clean high-citation OpenAlex domain before showing the full RAG demo:

```bash
RAG_SERVICE_KEY=<service-key> uv run python scripts/seed_openalex_cs_rag.py \
  --live \
  --vector-ingest \
  --local-embedding-backend sentence-transformers \
  --domain research-papers-cited1000-v2 \
  --state data/openalex-cs-cited1000-bge-st-kb-seed-state.json \
  --max-records 3863
```

The static export of `dist/` (~1.4 MB gzipped) is everything the FE needs.
JSON data files in `web/public/data/` are bundled; they reflect the CH state
at build time. To refresh them without rebuilding the bundle: run
`papers refresh-web && papers export-ch` on the backend host, then re-upload
the `dist/data/` folder (or trigger a rebuild).

## API URL priority (frontend)

When a React island needs the API base URL, it resolves in this order:
1. `PUBLIC_API_URL` — build-time env var (CF Pages / Vercel)
2. `window.__API_BASE__` — runtime override from `/api-config.js`
3. `http://127.0.0.1:8000` — local dev default

## Notes

- `clickhouse/init/02_functions.sql` auto-creates the `effective_year` /
  `effective_date` UDFs on a fresh CH boot. On a pre-existing data volume
  the init script is skipped — `deploy.sh` re-applies the UDFs manually.
- `paper_metadata_v2` and `paper_scores_v2` overlay tables are included in
  the dump, so corrected titles + full-corpus PageRank survive transport.
- OrbStack 2.1.3 on macOS 26 can have VM-backend instability. If `docker ps`
  randomly fails to reach the daemon, run `~/.orbstack/bin/orb start` from
  the CLI (the GUI doesn't always re-spawn the backend). Linux Docker daemons
  don't have this issue.
