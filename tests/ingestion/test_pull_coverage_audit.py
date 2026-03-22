"""Tests for ingestion/pull_coverage_audit.py."""

import csv
from pathlib import Path
from unittest.mock import MagicMock, call, patch

import pytest

from ingestion.pull_coverage_audit import (
    ENDPOINTS,
    LOW_COUNT_THRESHOLDS,
    _save_csv,
    fetch_record_count,
    run_coverage_audit,
)


# ---------------------------------------------------------------------------
# fetch_record_count
# ---------------------------------------------------------------------------


def test_fetch_record_count_returns_length_of_list():
    """fetch_record_count returns the number of records in the API response."""
    mock_session = MagicMock()
    with patch("ingestion.pull_coverage_audit.get_json", return_value=[{}, {}, {}]):
        count = fetch_record_count(mock_session, "/recruiting/players", "year", 2020)
    assert count == 3


def test_fetch_record_count_returns_zero_for_empty_list():
    """fetch_record_count returns 0 when the API returns an empty list."""
    mock_session = MagicMock()
    with patch("ingestion.pull_coverage_audit.get_json", return_value=[]):
        count = fetch_record_count(mock_session, "/recruiting/players", "year", 2005)
    assert count == 0


def test_fetch_record_count_returns_zero_on_exception():
    """fetch_record_count returns 0 (does not raise) when the API call fails."""
    mock_session = MagicMock()
    with patch(
        "ingestion.pull_coverage_audit.get_json",
        side_effect=Exception("Network error"),
    ):
        count = fetch_record_count(mock_session, "/draft/picks", "year", 2015)
    assert count == 0


def test_fetch_record_count_returns_zero_for_non_list_response():
    """fetch_record_count returns 0 when the API returns a non-list (unexpected)."""
    mock_session = MagicMock()
    with patch("ingestion.pull_coverage_audit.get_json", return_value={"error": "bad"}):
        count = fetch_record_count(mock_session, "/ratings/sp", "year", 2010)
    assert count == 0


def test_fetch_record_count_passes_correct_params():
    """fetch_record_count passes the correct year param to get_json."""
    mock_session = MagicMock()
    with patch("ingestion.pull_coverage_audit.get_json", return_value=[]) as mock_get:
        fetch_record_count(mock_session, "/stats/season/advanced", "year", 2019)
    mock_get.assert_called_once_with(
        mock_session, "/stats/season/advanced", params={"year": 2019}
    )


# ---------------------------------------------------------------------------
# _save_csv
# ---------------------------------------------------------------------------


def test_save_csv_writes_correct_headers_and_rows(tmp_path: Path):
    """_save_csv writes a valid CSV with the expected headers and data."""
    out_path = tmp_path / "audit.csv"
    results = [
        {"endpoint": "recruiting_players", "year": 2020, "record_count": 500, "flagged": False},
        {"endpoint": "draft_picks", "year": 2005, "record_count": 0, "flagged": True},
    ]
    _save_csv(results, out_path)

    assert out_path.exists()
    with out_path.open(newline="") as fh:
        reader = csv.DictReader(fh)
        rows = list(reader)

    assert rows[0]["endpoint"] == "recruiting_players"
    assert rows[0]["year"] == "2020"
    assert rows[0]["record_count"] == "500"
    assert rows[0]["flagged"] == "False"
    assert rows[1]["flagged"] == "True"


def test_save_csv_creates_parent_dirs(tmp_path: Path):
    """_save_csv creates nested parent directories if they do not exist."""
    out_path = tmp_path / "nested" / "dir" / "audit.csv"
    _save_csv([], out_path)
    assert out_path.exists()


# ---------------------------------------------------------------------------
# run_coverage_audit
# ---------------------------------------------------------------------------


def _make_count_side_effect(counts_by_label: dict[str, int]):
    """Return a side_effect callable that maps endpoint label → fixed count."""

    def _side_effect(session, endpoint, year_param, year):
        for label, path, _ in ENDPOINTS:
            if path == endpoint:
                return counts_by_label.get(label, 10)
        return 10

    return _side_effect


def test_run_coverage_audit_calls_build_session():
    """run_coverage_audit must call build_session with the provided api_key."""
    with patch("ingestion.pull_coverage_audit.build_session") as mock_build, \
         patch("ingestion.pull_coverage_audit.fetch_record_count", return_value=50), \
         patch("ingestion.pull_coverage_audit._save_csv"):
        mock_build.return_value = MagicMock()
        run_coverage_audit("test-key", years=[2020])
    mock_build.assert_called_once_with("test-key")


def test_run_coverage_audit_returns_all_rows(tmp_path: Path):
    """run_coverage_audit returns one row per (endpoint × year)."""
    years = [2020, 2021]
    audit_path = tmp_path / "audit.csv"

    with patch("ingestion.pull_coverage_audit.build_session", return_value=MagicMock()), \
         patch("ingestion.pull_coverage_audit.fetch_record_count", return_value=200):
        results = run_coverage_audit("test-key", years=years, audit_path=audit_path)

    expected_rows = len(ENDPOINTS) * len(years)
    assert len(results) == expected_rows


def test_run_coverage_audit_flags_zero_count(tmp_path: Path):
    """run_coverage_audit marks rows with 0 records as flagged=True."""
    audit_path = tmp_path / "audit.csv"

    with patch("ingestion.pull_coverage_audit.build_session", return_value=MagicMock()), \
         patch("ingestion.pull_coverage_audit.fetch_record_count", return_value=0):
        results = run_coverage_audit("test-key", years=[2005], audit_path=audit_path)

    assert all(r["flagged"] is True for r in results)


def test_run_coverage_audit_flags_low_count(tmp_path: Path):
    """run_coverage_audit flags rows below the LOW_COUNT_THRESHOLDS."""
    audit_path = tmp_path / "audit.csv"
    # recruiting_players threshold is 100; return 10 → should be flagged
    with patch("ingestion.pull_coverage_audit.build_session", return_value=MagicMock()), \
         patch("ingestion.pull_coverage_audit.fetch_record_count", return_value=10):
        results = run_coverage_audit("test-key", years=[2010], audit_path=audit_path)

    recruiting_row = next(r for r in results if r["endpoint"] == "recruiting_players")
    assert recruiting_row["flagged"] is True


def test_run_coverage_audit_does_not_flag_normal_count(tmp_path: Path):
    """run_coverage_audit does not flag rows with healthy record counts."""
    audit_path = tmp_path / "audit.csv"
    with patch("ingestion.pull_coverage_audit.build_session", return_value=MagicMock()), \
         patch("ingestion.pull_coverage_audit.fetch_record_count", return_value=500):
        results = run_coverage_audit("test-key", years=[2022], audit_path=audit_path)

    assert all(r["flagged"] is False for r in results)


def test_run_coverage_audit_saves_csv(tmp_path: Path):
    """run_coverage_audit writes a CSV file at the specified path."""
    audit_path = tmp_path / "out.csv"

    with patch("ingestion.pull_coverage_audit.build_session", return_value=MagicMock()), \
         patch("ingestion.pull_coverage_audit.fetch_record_count", return_value=100):
        run_coverage_audit("test-key", years=[2020], audit_path=audit_path)

    assert audit_path.exists()
    with audit_path.open() as fh:
        reader = csv.DictReader(fh)
        rows = list(reader)
    assert len(rows) == len(ENDPOINTS)


def test_run_coverage_audit_result_structure(tmp_path: Path):
    """Each result dict contains the required keys with correct types."""
    audit_path = tmp_path / "audit.csv"

    with patch("ingestion.pull_coverage_audit.build_session", return_value=MagicMock()), \
         patch("ingestion.pull_coverage_audit.fetch_record_count", return_value=75):
        results = run_coverage_audit("test-key", years=[2018], audit_path=audit_path)

    for row in results:
        assert "endpoint" in row
        assert "year" in row
        assert "record_count" in row
        assert "flagged" in row
        assert isinstance(row["year"], int)
        assert isinstance(row["record_count"], int)
        assert isinstance(row["flagged"], bool)


# ---------------------------------------------------------------------------
# Constants sanity checks
# ---------------------------------------------------------------------------


def test_all_endpoints_have_thresholds():
    """Every endpoint label in ENDPOINTS must have a threshold defined."""
    for label, _, _ in ENDPOINTS:
        assert label in LOW_COUNT_THRESHOLDS, f"Missing threshold for {label}"


def test_audit_years_range():
    """AUDIT_YEARS must cover 2005–2025 inclusive."""
    from ingestion.pull_coverage_audit import AUDIT_YEARS

    assert AUDIT_YEARS[0] == 2005
    assert AUDIT_YEARS[-1] == 2025
    assert len(AUDIT_YEARS) == 21
