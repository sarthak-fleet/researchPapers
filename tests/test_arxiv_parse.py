"""Unit tests for the pure parsing helpers in researchpapers.arxiv.

These cover arXiv id extraction, date parsing, and query-string building
without making any network calls.
"""

from datetime import date

import pytest

from researchpapers.arxiv import _build_query, _parse_arxiv_id, _parse_date


def test_parse_arxiv_id_old_style():
    assert _parse_arxiv_id("http://arxiv.org/abs/cs.LG/0703099") == "cs.LG/0703099"


def test_parse_arxiv_id_new_style_strips_version():
    assert _parse_arxiv_id("http://arxiv.org/abs/2401.12345v2") == "2401.12345"


def test_parse_arxiv_id_raises_on_garbage():
    with pytest.raises(ValueError):
        _parse_arxiv_id("https://example.com/no-arxiv-here")


def test_parse_date_handles_utc_z_suffix():
    assert _parse_date("2024-01-15T00:00:00Z") == date(2024, 1, 15)


def test_parse_date_returns_none_for_empty():
    assert _parse_date(None) is None
    assert _parse_date("") is None


def test_build_query_inclusive_date_range():
    q = _build_query("cs.LG", date(2024, 1, 1), date(2024, 1, 31))
    assert q == "cat:cs.LG AND submittedDate:[202401010000 TO 202401312359]"
