# AGENTS.md — researchPapers

## Shared Fleet Standard

Also read and follow the shared fleet-level agent standard at `../AGENTS.md`. Treat this repository as owned product code: protect production stability, keep changes scoped, verify work, and record durable follow-up tasks when something remains incomplete or blocked.

## Project

- **Stack**: ClickHouse, FastAPI, Astro 5 + React, sentence-transformers, MLX, spaCy.
- **Local dev**: Docker ClickHouse + `uv` per README · Astro frontend · FastAPI backend.
- **Checks**: CI workflows · see README quickstart.
- **Do not** run full corpus re-ingest or destructive ClickHouse ops without explicit approval.
