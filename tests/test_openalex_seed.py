from __future__ import annotations

import importlib.util
import sys
from pathlib import Path


SCRIPT_PATH = Path(__file__).resolve().parents[1] / "scripts" / "seed_openalex_cs_rag.py"
SPEC = importlib.util.spec_from_file_location("seed_openalex_cs_rag", SCRIPT_PATH)
assert SPEC and SPEC.loader
seed_openalex_cs_rag = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(seed_openalex_cs_rag)


def test_compact_work_reconstructs_abstract_and_keeps_links_only() -> None:
    record = seed_openalex_cs_rag.compact_work(
        {
            "id": "https://openalex.org/W1",
            "doi": "https://doi.org/10.1/example",
            "title": "A useful systems paper",
            "type": "article",
            "publication_year": 2024,
            "publication_date": "2024-01-01",
            "language": "en",
            "cited_by_count": 123,
            "referenced_works_count": 42,
            "abstract_inverted_index": {"Fast": [0], "systems": [1], "win": [2]},
            "primary_location": {
                "landing_page_url": "https://example.test/paper",
                "pdf_url": "https://example.test/paper.pdf",
                "is_oa": True,
                "source": {"id": "https://openalex.org/S1", "display_name": "Example Journal"},
            },
            "authorships": [
                {
                    "author": {"id": "https://openalex.org/A1", "display_name": "Ada Lovelace"},
                    "author_position": "first",
                    "institutions": [{"display_name": "Analytical Engines Lab"}],
                }
            ],
            "primary_topic": {
                "id": "https://openalex.org/T1",
                "display_name": "Distributed Systems",
                "subfield": {"display_name": "Computer Networks"},
                "field": {"display_name": "Computer Science"},
                "domain": {"display_name": "Physical Sciences"},
            },
            "topics": [{"display_name": "Distributed Systems"}],
            "biblio": {"volume": "1"},
            "updated_date": "2026-06-24T00:00:00",
        }
    )

    assert record["paper_id"] == "W1"
    assert record["abstract"] == "Fast systems win"
    assert record["citation_count"] == 123
    assert record["url"] == "https://example.test/paper"
    assert record["pdf_url"] == "https://example.test/paper.pdf"
    assert record["authors"][0]["name"] == "Ada Lovelace"
    assert record["primary_topic"] == "Distributed Systems"
    assert "rag_text" not in record
    assert "high-citation Computer Science research paper" in record["summary"]


def test_live_run_requires_explicit_bound(monkeypatch) -> None:
    monkeypatch.setattr(sys, "argv", ["seed_openalex_cs_rag.py", "--live"])

    assert seed_openalex_cs_rag.main() == 2


def test_openalex_filter_stays_cost_and_quality_bounded() -> None:
    assert "cited_by_count:>999" in seed_openalex_cs_rag.OPENALEX_FILTER
    assert "primary_topic.field.id:17" in seed_openalex_cs_rag.OPENALEX_FILTER
    assert "primary_location.source.type:journal|conference" in seed_openalex_cs_rag.OPENALEX_FILTER
    assert "cited1000" in seed_openalex_cs_rag.DEFAULT_STATE_PATH.name
    assert seed_openalex_cs_rag.DEFAULT_RECORD_TYPE == "PaperSignal"


def test_embedding_selection_can_be_passed_to_knowledgebase(monkeypatch, tmp_path) -> None:
    posted: list[dict] = []

    class FakeResponse:
        status_code = 201
        text = "{}"

        def raise_for_status(self) -> None:
            return None

        def json(self) -> dict:
            return {"chunks_indexed": 1, "file_id": "file-1"}

    def fake_fetch_openalex_page(*_args, **_kwargs):
        return {
            "meta": {"count": 1, "next_cursor": None},
            "results": [{"id": "https://openalex.org/W1", "title": "One", "cited_by_count": 1000}],
        }

    def fake_post_with_retries(*_args, json_body, **_kwargs):
        posted.append(json_body)
        return FakeResponse()

    monkeypatch.setenv("RAG_SERVICE_KEY", "test-key")
    monkeypatch.setattr(seed_openalex_cs_rag, "fetch_openalex_page", fake_fetch_openalex_page)
    monkeypatch.setattr(seed_openalex_cs_rag, "post_with_retries", fake_post_with_retries)
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "seed_openalex_cs_rag.py",
            "--live",
            "--max-records",
            "1",
            "--state",
            str(tmp_path / "seed-state.json"),
            "--embedding-model",
            "voyage-3.5-lite",
            "--embedding-provider",
            "voyage_ai",
        ],
    )

    assert seed_openalex_cs_rag.main() == 0
    assert posted[0]["embedding_model"] == "voyage-3.5-lite"
    assert posted[0]["embedding_provider"] == "voyage_ai"
    assert posted[1]["embedding_model"] == "voyage-3.5-lite"
    assert posted[1]["embedding_provider"] == "voyage_ai"


def test_vector_ingest_posts_local_embeddings_to_index(monkeypatch, tmp_path) -> None:
    posted: list[tuple[str, dict]] = []

    class FakeResponse:
        status_code = 201
        text = "{}"

        def raise_for_status(self) -> None:
            return None

        def json(self) -> dict:
            return {"upserted": 1}

    class FakeEmbedder:
        model_label = "CompendiumLabs/bge-base-en-v1.5-gguf/bge-base-en-v1.5-q8_0.gguf"

        def __init__(self, **_kwargs) -> None:
            return None

        def embed(self, texts: list[str]) -> list[list[float]]:
            assert texts
            return [[1.0] + [0.0] * 767 for _ in texts]

    def fake_fetch_openalex_page(*_args, **_kwargs):
        return {
            "meta": {"count": 1, "next_cursor": None},
            "results": [
                {
                    "id": "https://openalex.org/W1",
                    "title": "One useful retrieval paper",
                    "cited_by_count": 1000,
                    "abstract_inverted_index": {"Dense": [0], "retrieval": [1], "works": [2]},
                }
            ],
        }

    def fake_post_with_retries(_client, url, *, json_body, **_kwargs):
        posted.append((url, json_body))
        return FakeResponse()

    monkeypatch.setenv("RAG_SERVICE_KEY", "test-key")
    monkeypatch.setattr(seed_openalex_cs_rag, "fetch_openalex_page", fake_fetch_openalex_page)
    monkeypatch.setattr(seed_openalex_cs_rag, "post_with_retries", fake_post_with_retries)
    monkeypatch.setattr(
        seed_openalex_cs_rag,
        "ensure_vector_index",
        lambda *args, **kwargs: {"id": "index-1", "dimensions": 768},
    )
    monkeypatch.setattr(seed_openalex_cs_rag, "LmStudioEmbedder", FakeEmbedder)
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "seed_openalex_cs_rag.py",
            "--live",
            "--max-records",
            "1",
            "--state",
            str(tmp_path / "seed-state.json"),
            "--vector-ingest",
            "--batch-size",
            "1",
        ],
    )

    assert seed_openalex_cs_rag.main() == 0
    assert posted[0][0].endswith("/v1/kb/domains")
    assert posted[0][1]["embedding_model"] == "@cf/baai/bge-base-en-v1.5"
    assert posted[0][1]["embedding_provider"] == "workers_ai"
    assert posted[1][0].endswith("/v1/indexes/index-1/ingest-vectors")
    chunk = posted[1][1]["chunks"][0]
    assert chunk["id"] == "openalex-cs-cited1000:W1:chunk:0"
    assert len(chunk["embedding"]) == 768
    assert chunk["metadata"]["local_embedding_model"] == FakeEmbedder.model_label


def test_default_invocation_is_dry_run_without_secret(monkeypatch, capsys) -> None:
    def fake_fetch_openalex_page(*_args, **_kwargs):
        return {
            "meta": {"count": 1, "next_cursor": None},
            "results": [{"id": "https://openalex.org/W1", "title": "One", "cited_by_count": 100}],
        }

    monkeypatch.delenv("RAG_SERVICE_KEY", raising=False)
    monkeypatch.setattr(seed_openalex_cs_rag, "fetch_openalex_page", fake_fetch_openalex_page)
    monkeypatch.setattr(sys, "argv", ["seed_openalex_cs_rag.py"])

    assert seed_openalex_cs_rag.main() == 0
    assert "mode=dry-run" in capsys.readouterr().out
