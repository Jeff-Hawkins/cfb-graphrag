"""Tests for agents/data_validation/anomaly_checks.py.

Covers:
- check_duplicate_coach_nodes: returns list when duplicates found
- check_mentored_self_loops: returns list when self-loops found
- check_mentored_bidirectional_cycles: returns cycles
- check_null_role_abbr: returns edges with null role
- check_large_year_gaps: returns coaches with gaps > threshold
- check_graph_summary: returns dict of counts
"""

from unittest.mock import MagicMock

import pytest

from agents.data_validation.anomaly_checks import (
    check_duplicate_coach_nodes,
    check_graph_summary,
    check_large_year_gaps,
    check_mentored_bidirectional_cycles,
    check_mentored_self_loops,
    check_null_role_abbr,
)


# ---------------------------------------------------------------------------
# Mock driver helpers
# ---------------------------------------------------------------------------


def _mock_driver_list(rows: list[dict]) -> MagicMock:
    """Return a driver whose session.run() yields *rows*."""
    driver = MagicMock()
    session = MagicMock()
    driver.session.return_value.__enter__ = MagicMock(return_value=session)
    driver.session.return_value.__exit__ = MagicMock(return_value=False)
    mock_records = []
    for row in rows:
        rec = MagicMock()
        rec.data.return_value = row
        mock_records.append(rec)
    session.run.return_value = mock_records
    return driver


def _mock_driver_single(row: dict | None) -> MagicMock:
    """Return a driver whose session.run().single() returns *row*."""
    driver = MagicMock()
    session = MagicMock()
    driver.session.return_value.__enter__ = MagicMock(return_value=session)
    driver.session.return_value.__exit__ = MagicMock(return_value=False)
    mock_result = MagicMock()
    mock_result.single.return_value = row
    session.run.return_value = mock_result
    return driver


# ---------------------------------------------------------------------------
# check_duplicate_coach_nodes
# ---------------------------------------------------------------------------


class TestCheckDuplicateCoachNodes:
    def test_returns_duplicates(self):
        rows = [{"name": "John Smith", "coach_codes": [1, 2], "count": 2}]
        driver = _mock_driver_list(rows)
        result = check_duplicate_coach_nodes(driver)
        assert len(result) == 1
        assert result[0]["name"] == "John Smith"

    def test_returns_empty_when_no_duplicates(self):
        driver = _mock_driver_list([])
        result = check_duplicate_coach_nodes(driver)
        assert result == []

    def test_query_runs(self):
        driver = _mock_driver_list([])
        check_duplicate_coach_nodes(driver)
        session = driver.session().__enter__()
        assert session.run.called


# ---------------------------------------------------------------------------
# check_mentored_self_loops
# ---------------------------------------------------------------------------


class TestCheckMentoredSelfLoops:
    def test_returns_self_loops(self):
        rows = [{"coach_code": 42, "name": "Self-Looping Coach"}]
        driver = _mock_driver_list(rows)
        result = check_mentored_self_loops(driver)
        assert len(result) == 1
        assert result[0]["coach_code"] == 42

    def test_empty_in_clean_graph(self):
        driver = _mock_driver_list([])
        result = check_mentored_self_loops(driver)
        assert result == []


# ---------------------------------------------------------------------------
# check_mentored_bidirectional_cycles
# ---------------------------------------------------------------------------


class TestCheckMentoredBidirectionalCycles:
    def test_returns_cycles(self):
        rows = [
            {
                "coach_a_code": 1, "coach_a_name": "Coach A",
                "coach_b_code": 2, "coach_b_name": "Coach B",
            }
        ]
        driver = _mock_driver_list(rows)
        result = check_mentored_bidirectional_cycles(driver)
        assert len(result) == 1
        assert result[0]["coach_a_name"] == "Coach A"

    def test_empty_when_no_cycles(self):
        driver = _mock_driver_list([])
        result = check_mentored_bidirectional_cycles(driver)
        assert result == []


# ---------------------------------------------------------------------------
# check_null_role_abbr
# ---------------------------------------------------------------------------


class TestCheckNullRoleAbbr:
    def test_returns_null_edges(self):
        rows = [{"coach_code": 99, "name": "Bad Coach", "team": "State U", "year": 2010}]
        driver = _mock_driver_list(rows)
        result = check_null_role_abbr(driver)
        assert len(result) == 1
        assert result[0]["name"] == "Bad Coach"

    def test_empty_in_clean_graph(self):
        driver = _mock_driver_list([])
        result = check_null_role_abbr(driver)
        assert result == []

    def test_query_filters_mcillece_roles(self):
        driver = _mock_driver_list([])
        check_null_role_abbr(driver)
        session = driver.session().__enter__()
        query = session.run.call_args[0][0]
        assert "mcillece_roles" in query


# ---------------------------------------------------------------------------
# check_large_year_gaps
# ---------------------------------------------------------------------------


class TestCheckLargeYearGaps:
    def test_returns_large_gaps(self):
        rows = [
            {
                "coach_code": 5, "name": "Gap Coach",
                "team": "Gap U", "gap": 8,
                "gap_start": 2010, "gap_end": 2018,
            }
        ]
        driver = _mock_driver_list(rows)
        result = check_large_year_gaps(driver, max_gap=5)
        assert len(result) == 1
        assert result[0]["gap"] == 8

    def test_empty_when_no_large_gaps(self):
        driver = _mock_driver_list([])
        result = check_large_year_gaps(driver)
        assert result == []

    def test_max_gap_param_forwarded(self):
        driver = _mock_driver_list([])
        check_large_year_gaps(driver, max_gap=3)
        session = driver.session().__enter__()
        call_kwargs = session.run.call_args[1]
        assert call_kwargs.get("max_gap") == 3


# ---------------------------------------------------------------------------
# check_graph_summary
# ---------------------------------------------------------------------------


class TestCheckGraphSummary:
    def test_returns_expected_keys(self):
        """check_graph_summary must return counts for all labelled queries."""
        # Mock multiple session calls — one per query in check_graph_summary
        driver = MagicMock()
        session = MagicMock()
        driver.session.return_value.__enter__ = MagicMock(return_value=session)
        driver.session.return_value.__exit__ = MagicMock(return_value=False)

        single_mock = MagicMock()
        single_mock.__getitem__ = lambda self, k: 42
        result_mock = MagicMock()
        result_mock.single.return_value = single_mock
        session.run.return_value = result_mock

        summary = check_graph_summary(driver)
        assert isinstance(summary, dict)
        assert "Coach nodes" in summary
        assert "MENTORED edges" in summary
        assert "MENTORED STANDARD" in summary
        assert "MENTORED REVIEW_REVERSE" in summary

    def test_returns_zero_on_empty_single(self):
        """If single() returns None, count should be 0."""
        driver = MagicMock()
        session = MagicMock()
        driver.session.return_value.__enter__ = MagicMock(return_value=session)
        driver.session.return_value.__exit__ = MagicMock(return_value=False)
        result_mock = MagicMock()
        result_mock.single.return_value = None
        session.run.return_value = result_mock

        summary = check_graph_summary(driver)
        assert all(v == 0 for v in summary.values())
