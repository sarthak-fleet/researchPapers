#!/usr/bin/env python3
"""Seed Knowledgebase from OpenAlex canonical Computer Science papers.

Default corpus:
  type: article or preprint
  has_abstract: true
  cited_by_count > 999
  is_retracted: false
  primary_topic.field.id: 17  # Computer Science
  primary_location.source.type: journal or conference

This stores metadata, abstracts, and links only. It never downloads PDFs.
"""

from __future__ import annotations

import argparse
import gzip
import json
import math
import os
import sys
import time
from pathlib import Path
from typing import Any, Protocol

import httpx

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_BASE_URL = "https://knowledgebase.sarthakagrawal927.workers.dev"
DEFAULT_DOMAIN = "research-papers"
DEFAULT_RECORD_TYPE = "PaperSignal"
DEFAULT_STATE_PATH = ROOT / "data" / "openalex-cs-cited1000-kb-seed-state.json"
DEFAULT_SHARD_DIR = ROOT / "data" / "openalex-cs-cited1000-shards"
DEFAULT_VECTOR_EMBEDDING_MODEL = "@cf/baai/bge-base-en-v1.5"
DEFAULT_VECTOR_EMBEDDING_PROVIDER = "workers_ai"
DEFAULT_LOCAL_EMBEDDING_MODEL = "bge-base-en-v1.5"
DEFAULT_LOCAL_ST_MODEL = "BAAI/bge-base-en-v1.5"
DEFAULT_LOCAL_EMBEDDING_DIMENSIONS = 768
MAX_RECORD_INDEX_TEXT_CHARS = 1800
OPENALEX_WORKS_URL = "https://api.openalex.org/works"
OPENALEX_FILTER = ",".join(
    [
        "type:article|preprint",
        "has_abstract:true",
        "cited_by_count:>999",
        "is_retracted:false",
        "primary_topic.field.id:17",
        "primary_location.source.type:journal|conference",
    ]
)
OPENALEX_SELECT = ",".join(
    [
        "id",
        "doi",
        "title",
        "display_name",
        "publication_year",
        "publication_date",
        "ids",
        "language",
        "primary_location",
        "open_access",
        "type",
        "cited_by_count",
        "authorships",
        "abstract_inverted_index",
        "primary_topic",
        "topics",
        "referenced_works_count",
        "biblio",
        "updated_date",
    ]
)


def abstract_from_inverted_index(index: Any) -> str | None:
    if not isinstance(index, dict) or not index:
        return None
    positioned: list[tuple[int, str]] = []
    for token, positions in index.items():
        if not isinstance(token, str) or not isinstance(positions, list):
            continue
        for position in positions:
            if isinstance(position, int):
                positioned.append((position, token))
    if not positioned:
        return None
    return " ".join(token for _, token in sorted(positioned)).strip() or None


def nested_display_name(value: Any) -> str | None:
    if isinstance(value, dict) and isinstance(value.get("display_name"), str):
        return value["display_name"]
    return None


def compact_authors(authorships: Any, limit: int = 12) -> list[dict[str, Any]]:
    if not isinstance(authorships, list):
        return []
    authors: list[dict[str, Any]] = []
    for row in authorships[:limit]:
        if not isinstance(row, dict):
            continue
        author = row.get("author")
        authors.append(
            {
                "name": nested_display_name(author),
                "openalex_id": author.get("id") if isinstance(author, dict) else None,
                "position": row.get("author_position"),
                "institutions": [
                    name
                    for name in (
                        nested_display_name(inst)
                        for inst in (row.get("institutions") or [])
                        if isinstance(inst, dict)
                    )
                    if name
                ][:4],
            }
        )
    return authors


def topic_summary(work: dict[str, Any]) -> dict[str, Any]:
    primary = work.get("primary_topic") if isinstance(work.get("primary_topic"), dict) else {}
    topics = work.get("topics") if isinstance(work.get("topics"), list) else []
    return {
        "primary_topic": nested_display_name(primary),
        "primary_topic_id": primary.get("id") if isinstance(primary, dict) else None,
        "subfield": nested_display_name(primary.get("subfield")) if isinstance(primary, dict) else None,
        "field": nested_display_name(primary.get("field")) if isinstance(primary, dict) else None,
        "domain": nested_display_name(primary.get("domain")) if isinstance(primary, dict) else None,
        "topics": [
            name
            for name in (nested_display_name(topic) for topic in topics[:8] if isinstance(topic, dict))
            if name
        ],
    }


def landing_urls(work: dict[str, Any]) -> dict[str, Any]:
    primary = work.get("primary_location") if isinstance(work.get("primary_location"), dict) else {}
    source = primary.get("source") if isinstance(primary.get("source"), dict) else {}
    ids = work.get("ids") if isinstance(work.get("ids"), dict) else {}
    return {
        "url": primary.get("landing_page_url") or ids.get("doi") or work.get("doi") or work.get("id"),
        "pdf_url": primary.get("pdf_url"),
        "openalex_url": work.get("id"),
        "doi": work.get("doi") or ids.get("doi"),
        "source_name": source.get("display_name"),
        "source_id": source.get("id"),
        "is_open_access": bool(primary.get("is_oa")) if primary else None,
    }


def compact_work(work: dict[str, Any]) -> dict[str, Any]:
    title = str(work.get("title") or work.get("display_name") or "").strip()
    abstract = abstract_from_inverted_index(work.get("abstract_inverted_index"))
    urls = landing_urls(work)
    topics = topic_summary(work)
    authors = compact_authors(work.get("authorships"))
    author_names = [row["name"] for row in authors if row.get("name")]
    return {
        "record_kind": "openalex_research_paper",
        "collection": "openalex_cs_cited_1000",
        "openalex_id": work.get("id"),
        "paper_id": str(work.get("id") or "").removeprefix("https://openalex.org/"),
        "type": work.get("type"),
        "title": title,
        "abstract": abstract,
        "publication_year": work.get("publication_year"),
        "publication_date": work.get("publication_date"),
        "citation_count": work.get("cited_by_count"),
        "referenced_works_count": work.get("referenced_works_count"),
        "language": work.get("language"),
        "authors": authors,
        "author_names": author_names,
        "primary_topic": topics["primary_topic"],
        "primary_topic_id": topics["primary_topic_id"],
        "subfield": topics["subfield"],
        "field": topics["field"],
        "domain": topics["domain"],
        "topics": topics["topics"],
        "url": urls["url"],
        "pdf_url": urls["pdf_url"],
        "openalex_url": urls["openalex_url"],
        "doi": urls["doi"],
        "source_name": urls["source_name"],
        "source_id": urls["source_id"],
        "is_open_access": urls["is_open_access"],
        "biblio": work.get("biblio") if isinstance(work.get("biblio"), dict) else None,
        "updated_date": work.get("updated_date"),
        "summary": " | ".join(
            part
            for part in [
                "high-citation Computer Science research paper",
                title,
                f"{work.get('cited_by_count')} citations" if work.get("cited_by_count") is not None else "",
                f"topic {topics['primary_topic']}" if topics["primary_topic"] else "",
                f"authors {', '.join(author_names[:4])}" if author_names else "",
                abstract[:600] if abstract else "",
            ]
            if part
        ),
    }


def string_field(record: dict[str, Any], key: str) -> str | None:
    value = record.get(key)
    if isinstance(value, str) and value.strip():
        return value.strip()
    return None


def list_field(record: dict[str, Any], key: str) -> list[str]:
    value = record.get(key)
    if not isinstance(value, list):
        return []
    return [item.strip() for item in value if isinstance(item, str) and item.strip()]


def clamp_index_text(value: str) -> str:
    if len(value) <= MAX_RECORD_INDEX_TEXT_CHARS:
        return value
    clipped = value[:MAX_RECORD_INDEX_TEXT_CHARS].rsplit(" ", 1)[0].rstrip()
    return f"{clipped or value[:MAX_RECORD_INDEX_TEXT_CHARS].rstrip()}..."


def structured_record_index_text(record: dict[str, Any]) -> str:
    rag_text = string_field(record, "rag_text")
    if rag_text:
        return clamp_index_text(rag_text)

    author_names = list_field(record, "author_names")
    topics = list_field(record, "topics")
    rows = [
        ("Title", string_field(record, "title")),
        ("Abstract", string_field(record, "abstract")),
        ("Summary", string_field(record, "summary")),
        ("Authors", ", ".join(author_names) if author_names else None),
        ("Primary topic", string_field(record, "primary_topic")),
        ("Subfield", string_field(record, "subfield")),
        ("Source", string_field(record, "source_name")),
        (
            "Publication year",
            None if record.get("publication_year") is None else str(record.get("publication_year")),
        ),
        (
            "Citations",
            None if record.get("citation_count") is None else str(record.get("citation_count")),
        ),
        ("Topics", ", ".join(topics) if topics else None),
        ("URL", string_field(record, "url")),
        ("PDF link", string_field(record, "pdf_url")),
        ("OpenAlex URL", string_field(record, "openalex_url")),
        ("DOI", string_field(record, "doi")),
    ]
    lines = [f"{label}: {value}" for label, value in rows if value]
    return clamp_index_text("\n".join(lines) if lines else json.dumps(record, sort_keys=True))


def chunk_text(text: str, *, size: int = 2000, overlap: int = 200) -> list[str]:
    size = max(100, min(size, 8000))
    overlap = max(0, min(overlap, size - 1))
    chunks_out: list[str] = []
    if not text:
        return chunks_out

    current = ""
    for paragraph in text.split("\n\n"):
        if len(current) + len(paragraph) <= size:
            separator = "\n\n" if current else ""
            current += f"{separator}{paragraph}"
            continue

        if current:
            chunks_out.append(current)
            current = ""

        if len(paragraph) > size:
            remaining = paragraph
            while remaining:
                chunks_out.append(remaining[:size])
                remaining = remaining[size - overlap :]
                if len(remaining) <= overlap:
                    break
        else:
            current = paragraph

    if current:
        chunks_out.append(current)
    return chunks_out


def l2_normalize(vector: list[float]) -> list[float]:
    norm = math.sqrt(sum(value * value for value in vector))
    if norm <= 0:
        return vector
    return [value / norm for value in vector]


class LocalEmbedder(Protocol):
    model_label: str

    def embed(self, texts: list[str]) -> list[list[float]]:
        ...


class LmStudioEmbedder:
    def __init__(
        self,
        *,
        client: httpx.Client,
        base_url: str,
        model: str,
        expected_dimensions: int,
    ) -> None:
        self.client = client
        self.base_url = base_url.rstrip("/")
        self.requested_model = model
        self.expected_dimensions = expected_dimensions
        self.model_label = self._resolve_model(model)

    def _resolve_model(self, requested: str) -> str:
        try:
            response = self.client.get(f"{self.base_url}/models")
            response.raise_for_status()
            rows = response.json().get("data")
        except Exception:
            return requested
        if not isinstance(rows, list):
            return requested
        ids = [str(row.get("id") or "") for row in rows if isinstance(row, dict)]
        if requested in ids:
            return requested
        needle = requested.lower()
        for model_id in ids:
            if needle in model_id.lower() or "bge-base-en-v1.5" in model_id.lower():
                return model_id
        return requested

    def embed(self, texts: list[str]) -> list[list[float]]:
        if not texts:
            return []
        response = self.client.post(
            f"{self.base_url}/embeddings",
            json={"model": self.model_label, "input": texts},
        )
        response.raise_for_status()
        rows = response.json().get("data")
        if not isinstance(rows, list):
            raise RuntimeError("LM Studio embedding response missing data array")
        ordered = sorted(rows, key=lambda row: row.get("index", 0) if isinstance(row, dict) else 0)
        vectors: list[list[float]] = []
        for index, row in enumerate(ordered):
            if not isinstance(row, dict) or not isinstance(row.get("embedding"), list):
                raise RuntimeError(f"LM Studio embedding response row {index} missing embedding")
            vector = [float(value) for value in row["embedding"]]
            if len(vector) != self.expected_dimensions:
                raise RuntimeError(
                    "LM Studio embedding dimension mismatch: "
                    f"expected {self.expected_dimensions}, got {len(vector)}"
                )
            vectors.append(l2_normalize(vector))
        if len(vectors) != len(texts):
            raise RuntimeError(f"LM Studio returned {len(vectors)} vectors for {len(texts)} texts")
        return vectors


class SentenceTransformersEmbedder:
    def __init__(self, *, model: str, batch_size: int, expected_dimensions: int) -> None:
        from sentence_transformers import SentenceTransformer

        self.model_label = model
        self.batch_size = batch_size
        self.expected_dimensions = expected_dimensions
        self.model = SentenceTransformer(model)

    def embed(self, texts: list[str]) -> list[list[float]]:
        embeddings = self.model.encode(
            texts,
            batch_size=self.batch_size,
            normalize_embeddings=True,
            show_progress_bar=False,
        )
        vectors = [embedding.tolist() for embedding in embeddings]
        for index, vector in enumerate(vectors):
            if len(vector) != self.expected_dimensions:
                raise RuntimeError(
                    "sentence-transformers embedding dimension mismatch: "
                    f"expected {self.expected_dimensions}, got {len(vector)} at row {index}"
                )
        return vectors


def vector_metadata(
    record: dict[str, Any],
    *,
    domain: str,
    record_type: str,
    local_embedding_model: str,
) -> dict[str, Any]:
    return {
        "domain": domain,
        "entity_type": record_type,
        "source": "openalex",
        "record_kind": record.get("record_kind"),
        "collection": record.get("collection"),
        "paper_id": record.get("paper_id"),
        "openalex_id": record.get("openalex_id"),
        "title": record.get("title"),
        "publication_year": record.get("publication_year"),
        "citation_count": record.get("citation_count"),
        "primary_topic": record.get("primary_topic"),
        "subfield": record.get("subfield"),
        "field": record.get("field"),
        "source_name": record.get("source_name"),
        "url": record.get("url"),
        "pdf_url": record.get("pdf_url"),
        "doi": record.get("doi"),
        "author_names": list_field(record, "author_names")[:8],
        "topics": list_field(record, "topics")[:8],
        "local_embedding_model": local_embedding_model,
    }


def vector_chunks_for_records(
    records: list[dict[str, Any]],
    *,
    domain: str,
    record_type: str,
    embedder: LocalEmbedder,
    chunk_size: int,
    chunk_overlap: int,
) -> list[dict[str, Any]]:
    pending: list[tuple[dict[str, Any], int, str, str, str]] = []
    for record in records:
        paper_id = str(record.get("paper_id") or safe_filename(str(record.get("openalex_id") or "")))
        document_id = f"openalex-cs-cited1000:{paper_id}"
        content = structured_record_index_text(record)
        for chunk_index, chunk in enumerate(
            chunk_text(content, size=chunk_size, overlap=chunk_overlap)
        ):
            pending.append((record, chunk_index, chunk, document_id, content))

    embeddings = embedder.embed([row[2] for row in pending])
    out: list[dict[str, Any]] = []
    for (record, chunk_index, chunk, document_id, content), embedding in zip(
        pending, embeddings, strict=True
    ):
        out.append(
            {
                "id": f"{document_id}:chunk:{chunk_index}",
                "document_id": document_id,
                "document_content": content,
                "document_external_id": record.get("openalex_id") or record.get("paper_id"),
                "content": chunk,
                "embedding": embedding,
                "chunk_index": chunk_index,
                "metadata": vector_metadata(
                    record,
                    domain=domain,
                    record_type=record_type,
                    local_embedding_model=embedder.model_label,
                ),
            }
        )
    return out


def ensure_vector_index(
    client: httpx.Client,
    *,
    base_url: str,
    key: str,
    domain: str,
    embedding_model: str,
    embedding_provider: str,
    expected_dimensions: int,
    attempts: int,
) -> dict[str, Any]:
    headers = {"Authorization": f"Bearer {key}", "Content-Type": "application/json"}
    indexes_resp = client.get(f"{base_url}/v1/indexes", headers=headers)
    indexes_resp.raise_for_status()
    indexes = indexes_resp.json().get("data")
    external_id = f"kb:{domain}"
    if isinstance(indexes, list):
        for index in indexes:
            if isinstance(index, dict) and index.get("external_id") == external_id:
                dimensions = int(index.get("dimensions") or 0)
                if dimensions != expected_dimensions:
                    raise RuntimeError(
                        f"existing index {index.get('id')} is {dimensions}d, "
                        f"expected {expected_dimensions}d"
                    )
                return index

    create_resp = post_with_retries(
        client,
        f"{base_url}/v1/indexes",
        headers=headers,
        json_body={
            "name": f"Knowledgebase {domain}",
            "external_id": external_id,
            "embedding_model": embedding_model,
            "embedding_provider": embedding_provider,
        },
        attempts=attempts,
    )
    create_resp.raise_for_status()
    created = create_resp.json()
    dimensions = int(created.get("dimensions") or 0)
    if dimensions != expected_dimensions:
        raise RuntimeError(
            f"created index {created.get('id')} is {dimensions}d, expected {expected_dimensions}d"
        )
    return created


def load_state(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {
            "cursor": "*",
            "page_offset": 0,
            "pages": 0,
            "records_posted": 0,
            "batches_posted": 0,
        }
    return json.loads(path.read_text())


def save_state(path: Path, state: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(state, indent=2, sort_keys=True))


def post_with_retries(
    client: httpx.Client,
    url: str,
    *,
    headers: dict[str, str],
    json_body: dict[str, Any],
    attempts: int,
) -> httpx.Response:
    last_error: Exception | None = None
    for attempt in range(1, attempts + 1):
        try:
            response = client.post(url, headers=headers, json=json_body)
            if response.status_code in {408, 429, 500, 502, 503, 504} and attempt < attempts:
                retry_after = response.headers.get("retry-after")
                sleep_s = float(retry_after) if retry_after and retry_after.isdigit() else min(2**attempt, 30)
                print(f"retrying HTTP {response.status_code} in {sleep_s:.1f}s", flush=True)
                time.sleep(sleep_s)
                continue
            return response
        except (httpx.TimeoutException, httpx.NetworkError, httpx.RemoteProtocolError) as exc:
            last_error = exc
            if attempt >= attempts:
                raise
            sleep_s = min(2**attempt, 30)
            print(f"retrying {type(exc).__name__} in {sleep_s:.1f}s", flush=True)
            time.sleep(sleep_s)
    if last_error:
        raise last_error
    raise RuntimeError("unreachable retry state")


def chunks(items: list[dict[str, Any]], size: int) -> list[list[dict[str, Any]]]:
    return [items[index : index + size] for index in range(0, len(items), size)]


class JsonlGzipShardWriter:
    def __init__(self, shard_dir: Path, *, records_per_shard: int) -> None:
        if records_per_shard < 1:
            raise ValueError("records_per_shard must be positive")
        self.shard_dir = shard_dir
        self.records_per_shard = records_per_shard
        self.buffer: list[dict[str, Any]] = []
        self.shards_written = 0
        self.records_written = 0
        self.shard_dir.mkdir(parents=True, exist_ok=True)

    def add_many(self, records: list[dict[str, Any]]) -> None:
        for record in records:
            self.buffer.append(record)
            if len(self.buffer) >= self.records_per_shard:
                self.flush()

    def flush(self) -> None:
        if not self.buffer:
            return
        self.shards_written += 1
        first_id = str(self.buffer[0].get("paper_id") or "unknown")
        last_id = str(self.buffer[-1].get("paper_id") or "unknown")
        path = self.shard_dir / (
            f"openalex-cs-cited1000-{self.shards_written:05d}-"
            f"{safe_filename(first_id)}-{safe_filename(last_id)}.jsonl.gz"
        )
        with gzip.open(path, "wt", encoding="utf-8", compresslevel=6) as handle:
            for record in self.buffer:
                handle.write(json.dumps(record, separators=(",", ":"), ensure_ascii=False))
                handle.write("\n")
        self.records_written += len(self.buffer)
        print(f"wrote shard {path} records={len(self.buffer)}", flush=True)
        self.buffer.clear()


def safe_filename(value: str) -> str:
    cleaned = "".join(ch if ch.isalnum() or ch in {"-", "_"} else "-" for ch in value)
    return cleaned.strip("-")[:80] or "unknown"


def fetch_openalex_page(
    client: httpx.Client,
    *,
    cursor: str,
    per_page: int,
    mailto: str | None,
) -> dict[str, Any]:
    params = {
        "filter": OPENALEX_FILTER,
        "select": OPENALEX_SELECT,
        "sort": "cited_by_count:desc",
        "per-page": str(per_page),
        "cursor": cursor,
    }
    if mailto:
        params["mailto"] = mailto
    response = client.get(OPENALEX_WORKS_URL, params=params)
    response.raise_for_status()
    return response.json()


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--base-url", default=os.environ.get("RAG_SERVICE_URL", DEFAULT_BASE_URL))
    parser.add_argument("--domain", default=os.environ.get("RAG_DOMAIN", DEFAULT_DOMAIN))
    parser.add_argument("--record-type", default=os.environ.get("RAG_RECORD_TYPE", DEFAULT_RECORD_TYPE))
    parser.add_argument("--embedding-model", default=os.environ.get("RAG_EMBEDDING_MODEL"))
    parser.add_argument("--embedding-provider", default=os.environ.get("RAG_EMBEDDING_PROVIDER"))
    parser.add_argument("--vector-ingest", action="store_true")
    parser.add_argument(
        "--local-embedding-backend",
        choices=["lmstudio", "sentence-transformers"],
        default=os.environ.get("RAG_LOCAL_EMBEDDING_BACKEND", "lmstudio"),
    )
    parser.add_argument(
        "--local-embedding-model",
        default=os.environ.get("RAG_LOCAL_EMBEDDING_MODEL"),
    )
    parser.add_argument(
        "--lmstudio-url",
        default=os.environ.get("LMSTUDIO_BASE_URL", "http://127.0.0.1:1234/v1"),
    )
    parser.add_argument("--expected-dimensions", type=int, default=DEFAULT_LOCAL_EMBEDDING_DIMENSIONS)
    parser.add_argument("--vector-batch-size", type=int, default=50)
    parser.add_argument("--local-embedding-batch-size", type=int, default=32)
    parser.add_argument("--chunk-size", type=int, default=2000)
    parser.add_argument("--chunk-overlap", type=int, default=200)
    parser.add_argument("--state", type=Path, default=DEFAULT_STATE_PATH)
    parser.add_argument("--per-page", type=int, default=200)
    parser.add_argument("--batch-size", type=int, default=10)
    parser.add_argument("--max-records", type=int, default=None)
    parser.add_argument("--run-budget", type=int, default=500)
    parser.add_argument("--timeout", type=float, default=180.0)
    parser.add_argument("--retries", type=int, default=5)
    parser.add_argument("--sleep", type=float, default=2.0)
    parser.add_argument("--write-shards", action="store_true")
    parser.add_argument("--shard-dir", type=Path, default=DEFAULT_SHARD_DIR)
    parser.add_argument("--shard-records", type=int, default=1000)
    parser.add_argument("--live", action="store_true")
    parser.add_argument("--full-run", action="store_true")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--reset-state", action="store_true")
    parser.add_argument("--mailto", default=os.environ.get("CONTACT_EMAIL"))
    args = parser.parse_args()

    if args.per_page < 1 or args.per_page > 200:
        print("--per-page must be between 1 and 200", file=sys.stderr)
        return 2
    if args.batch_size < 1 or args.batch_size > 200:
        print("--batch-size must be between 1 and 200", file=sys.stderr)
        return 2
    if args.vector_batch_size < 1 or args.vector_batch_size > 200:
        print("--vector-batch-size must be between 1 and 200", file=sys.stderr)
        return 2
    if args.local_embedding_batch_size < 1 or args.local_embedding_batch_size > 200:
        print("--local-embedding-batch-size must be between 1 and 200", file=sys.stderr)
        return 2
    if args.expected_dimensions < 1:
        print("--expected-dimensions must be positive", file=sys.stderr)
        return 2
    if args.run_budget < 1:
        print("--run-budget must be positive", file=sys.stderr)
        return 2
    if args.shard_records < 1:
        print("--shard-records must be positive", file=sys.stderr)
        return 2
    if args.full_run and args.max_records is not None:
        print("--full-run and --max-records are mutually exclusive", file=sys.stderr)
        return 2
    if not args.live:
        args.dry_run = True
    if args.live and not args.full_run and args.max_records is None:
        print(
            "live seeding requires --max-records N, or --full-run for the complete corpus",
            file=sys.stderr,
        )
        return 2

    if args.reset_state and args.state.exists():
        args.state.unlink()

    state = load_state(args.state)
    with httpx.Client(timeout=args.timeout) as client:
        first_page = fetch_openalex_page(
            client,
            cursor=str(state.get("cursor") or "*"),
            per_page=args.per_page,
            mailto=args.mailto,
        )
        total = int((first_page.get("meta") or {}).get("count") or 0)
        print(
            f"OpenAlex corpus count={total} filter={OPENALEX_FILTER} "
            f"domain={args.domain} cursor={state.get('cursor')} "
            f"mode={'live' if args.live else 'dry-run'} "
            f"batch_size={args.batch_size} sleep={args.sleep}s run_budget={args.run_budget} "
            f"write_shards={args.write_shards} record_type={args.record_type} "
            f"embedding_model={args.embedding_model or 'domain-default'} "
            f"vector_ingest={args.vector_ingest}",
            flush=True,
        )
        if args.dry_run:
            sample = [compact_work(row) for row in (first_page.get("results") or [])[:2]]
            print(json.dumps({"sample_records": sample}, indent=2))
            return 0

        shard_writer = (
            JsonlGzipShardWriter(args.shard_dir, records_per_shard=args.shard_records)
            if args.write_shards
            else None
        )

        key = os.environ.get("RAG_SERVICE_KEY")
        if not key:
            print("RAG_SERVICE_KEY is required for live seed", file=sys.stderr)
            return 2

        base_url = args.base_url.rstrip("/")
        if args.vector_ingest:
            args.embedding_model = args.embedding_model or DEFAULT_VECTOR_EMBEDDING_MODEL
            args.embedding_provider = args.embedding_provider or DEFAULT_VECTOR_EMBEDDING_PROVIDER
        embedding_selection = {
            **({"embedding_model": args.embedding_model.strip()} if args.embedding_model and args.embedding_model.strip() else {}),
            **({"embedding_provider": args.embedding_provider.strip()} if args.embedding_provider and args.embedding_provider.strip() else {}),
        }
        domain_resp = post_with_retries(
            client,
            f"{base_url}/v1/kb/domains",
            headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"},
            json_body={
                "name": args.domain,
                "description": (
                    "OpenAlex high-citation Computer Science research papers: "
                    "article/preprint, abstract present, >999 citations, not retracted. "
                    "Metadata/abstract/link only; PDFs are not stored."
                ),
                **embedding_selection,
            },
            attempts=args.retries,
        )
        if domain_resp.status_code not in {200, 201, 409}:
            domain_resp.raise_for_status()

        vector_index: dict[str, Any] | None = None
        embedder: LocalEmbedder | None = None
        if args.vector_ingest:
            vector_index = ensure_vector_index(
                client,
                base_url=base_url,
                key=key,
                domain=args.domain,
                embedding_model=args.embedding_model,
                embedding_provider=args.embedding_provider,
                expected_dimensions=args.expected_dimensions,
                attempts=args.retries,
            )
            if args.local_embedding_backend == "lmstudio":
                embedder = LmStudioEmbedder(
                    client=client,
                    base_url=args.lmstudio_url,
                    model=args.local_embedding_model or DEFAULT_LOCAL_EMBEDDING_MODEL,
                    expected_dimensions=args.expected_dimensions,
                )
            else:
                embedder = SentenceTransformersEmbedder(
                    model=args.local_embedding_model or DEFAULT_LOCAL_ST_MODEL,
                    batch_size=args.local_embedding_batch_size,
                    expected_dimensions=args.expected_dimensions,
                )
            print(
                f"vector ingest index={vector_index.get('id')} dimensions={vector_index.get('dimensions')} "
                f"local_backend={args.local_embedding_backend} local_model={embedder.model_label}",
                flush=True,
            )

        page = first_page
        run_posted = 0
        while True:
            raw_results = page.get("results") if isinstance(page.get("results"), list) else []
            page_offset = int(state.get("page_offset") or 0)
            if "page_offset" not in state and int(state.get("pages") or 0) == 0:
                page_offset = int(state.get("records_posted") or 0) % args.per_page
                state["page_offset"] = page_offset
            if page_offset > 0:
                raw_results = raw_results[page_offset:]
            records = [compact_work(row) for row in raw_results if isinstance(row, dict)]
            if args.max_records is not None:
                remaining = max(0, args.max_records - int(state.get("records_posted") or 0))
                records = records[:remaining]
            budget_remaining = max(0, args.run_budget - run_posted)
            records = records[:budget_remaining]
            if not records:
                break
            if shard_writer:
                shard_writer.add_many(records)

            for batch in chunks(records, args.batch_size):
                state["batches_posted"] = int(state.get("batches_posted") or 0) + 1
                batch_no = int(state["batches_posted"])
                ids = [str(row.get("paper_id") or row.get("openalex_id")) for row in batch]
                if args.vector_ingest:
                    if vector_index is None or embedder is None:
                        raise RuntimeError("vector ingest was not initialized")
                    vector_chunks = vector_chunks_for_records(
                        batch,
                        domain=args.domain,
                        record_type=args.record_type,
                        embedder=embedder,
                        chunk_size=args.chunk_size,
                        chunk_overlap=args.chunk_overlap,
                    )
                    upserted = 0
                    for vector_batch in chunks(vector_chunks, args.vector_batch_size):
                        resp = post_with_retries(
                            client,
                            f"{base_url}/v1/indexes/{vector_index['id']}/ingest-vectors",
                            headers={
                                "Authorization": f"Bearer {key}",
                                "Content-Type": "application/json",
                            },
                            json_body={"chunks": vector_batch},
                            attempts=args.retries,
                        )
                        if resp.status_code >= 400:
                            print(
                                f"vector ingest failed HTTP {resp.status_code}: {resp.text[:1000]}",
                                file=sys.stderr,
                            )
                        resp.raise_for_status()
                        upserted += int(resp.json().get("upserted") or 0)
                    body = {"chunks_indexed": upserted, "file_id": None}
                else:
                    resp = post_with_retries(
                        client,
                        f"{base_url}/v1/kb/ingest/record",
                        headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"},
                        json_body={
                            "domain": args.domain,
                            "type": args.record_type,
                            "data": batch,
                            "idempotency_key": f"openalex-cs-cited1000-v1-{ids[0]}-{ids[-1]}-{len(batch)}",
                            **embedding_selection,
                        },
                        attempts=args.retries,
                    )
                    if resp.status_code >= 400:
                        print(f"ingest failed HTTP {resp.status_code}: {resp.text[:1000]}", file=sys.stderr)
                    resp.raise_for_status()
                    body = resp.json()
                state["records_posted"] = int(state.get("records_posted") or 0) + len(batch)
                state["page_offset"] = int(state.get("page_offset") or 0) + len(batch)
                run_posted += len(batch)
                save_state(args.state, state)
                print(
                    f"batch {batch_no}: records={len(batch)} total_posted={state['records_posted']} "
                    f"chunks_indexed={body.get('chunks_indexed')} file_id={body.get('file_id')}"
                    f"{' idempotent' if body.get('idempotent_replay') else ''}",
                    flush=True,
                )
                if args.sleep > 0:
                    time.sleep(args.sleep)
                if args.max_records is not None and int(state["records_posted"]) >= args.max_records:
                    if shard_writer:
                        shard_writer.flush()
                    print("max-records reached", flush=True)
                    return 0
                if run_posted >= args.run_budget:
                    if shard_writer:
                        shard_writer.flush()
                    print("run-budget reached", flush=True)
                    return 0

            meta = page.get("meta") if isinstance(page.get("meta"), dict) else {}
            next_cursor = meta.get("next_cursor")
            state["cursor"] = next_cursor
            state["page_offset"] = 0
            state["pages"] = int(state.get("pages") or 0) + 1
            save_state(args.state, state)
            if not next_cursor:
                break
            page = fetch_openalex_page(
                client,
                cursor=str(next_cursor),
                per_page=args.per_page,
                mailto=args.mailto,
            )

        if shard_writer:
            shard_writer.flush()
    print(f"seed complete: records_posted={state.get('records_posted')} pages={state.get('pages')}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
