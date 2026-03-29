"""Tests for agents/data_validation/validate.py.

Covers:
- check_tenure: found and not-found cases with mocked driver
- check_mentored: expect_edge=True/False with found/not-found cases
- check_coached_at_edge_counts: sparse and dense anomaly detection
- check_mentored_overlap_sanity: flags edges with <2 shared seasons
- _load_ground_truth: YAML loads with expected top-level keys
"""

from pathlib import Path
from unittest.mock import MagicMock

import pytest

from agents.data_validation.validate import (
    check_coached_at_edge_counts,
    check_mentored,
    check_mentored_overlap_sanity,
    check_tenure,
)


# ---------------------------------------------------------------------------
# Mock driver helpers
# ---------------------------------------------------------------------------


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


# ---------------------------------------------------------------------------
# check_tenure
# ---------------------------------------------------------------------------


class TestCheckTenure:
    def test_returns_ok_when_edges_found(self):
        row = {"n": 3, "sample_years": [2008, 2009, 2010]}
        driver = _mock_driver_single(row)
        entry = {"coach": "Kirby Smart", "team": "Alabama", "role": "DC",
                 "start_year": 2008, "end_year": 2015}
        result = check_tenure(driver, entry)
        assert result["ok"] is True
        assert "3" in result["detail"]

    def test_returns_failure_when_no_edges(self):
        row = {"n": 0, "sample_years": []}
        driver = _mock_driver_single(row)
        entry = {"coach": "Nick Saban", "team": "Michigan", "role": "HC",
                 "start_year": 2007, "end_year": 2023}
        result = check_tenure(driver, entry)
        assert result["ok"] is False
        assert "Nick Saban" in result["detail"]
        assert "Michigan" in result["detail"]

    def test_entry_preserved_in_result(self):
        row = {"n": 1, "sample_years": [2010]}
        driver = _mock_driver_single(row)
        entry = {"coach": "A Coach", "team": "A Team", "start_year": 2010, "end_year": 2012}
        result = check_tenure(driver, entry)
        assert result["entry"] is entry

    def test_query_sent_to_session(self):
        driver = _mock_driver_single({"n": 0, "sample_years": []})
        entry = {"coach": "Test Coach", "team": "Test U", "role": "HC",
                 "start_year": 2010, "end_year": 2015}
        check_tenure(driver, entry)
        session = driver.session().__enter__()
        assert session.run.called

    def test_tenure_without_role_still_checks(self):
        """Entries without a role field should run without crashing."""
        row = {"n": 5, "sample_years": [2015]}
        driver = _mock_driver_single(row)
        entry = {"coach": "Will Muschamp", "team": "Alabama",
                 "start_year": 2016, "end_year": 2017}
        result = check_tenure(driver, entry)
        assert result["ok"] is True


# ---------------------------------------------------------------------------
# check_mentored
# ---------------------------------------------------------------------------


class TestCheckMentored:
    def test_expect_present_and_found(self):
        row = {"n": 1, "flag": "STANDARD"}
        driver = _mock_driver_single(row)
        entry = {"mentor": "Nick Saban", "mentee": "Kirby Smart", "rationale": "..."}
        result = check_mentored(driver, entry, expect_edge=True)
        assert result["ok"] is True
        assert "STANDARD" in result["detail"]

    def test_expect_present_but_missing(self):
        row = {"n": 0, "flag": None}
        driver = _mock_driver_single(row)
        entry = {"mentor": "Nick Saban", "mentee": "Jim McElwain", "rationale": "..."}
        result = check_mentored(driver, entry, expect_edge=True)
        assert result["ok"] is False
        assert "MISSING" in result["detail"]

    def test_expect_absent_and_correctly_absent(self):
        row = {"n": 0, "flag": None}
        driver = _mock_driver_single(row)
        entry = {"mentor": "Kirby Smart", "mentee": "Will Muschamp", "rationale": "prior HC"}
        result = check_mentored(driver, entry, expect_edge=False)
        assert result["ok"] is True
        assert "absent" in result["detail"]

    def test_expect_absent_but_edge_exists(self):
        row = {"n": 1, "flag": "STANDARD"}
        driver = _mock_driver_single(row)
        entry = {"mentor": "Kirby Smart", "mentee": "Will Muschamp", "rationale": "prior HC"}
        result = check_mentored(driver, entry, expect_edge=False)
        assert result["ok"] is False
        assert "should NOT exist" in result["detail"]

    def test_entry_preserved(self):
        row = {"n": 1, "flag": "STANDARD"}
        driver = _mock_driver_single(row)
        entry = {"mentor": "A", "mentee": "B", "rationale": "test"}
        result = check_mentored(driver, entry, expect_edge=True)
        assert result["entry"] is entry


# ---------------------------------------------------------------------------
# check_coached_at_edge_counts
# ---------------------------------------------------------------------------


class TestCheckCoachedAtEdgeCounts:
    def test_sparse_coach_flagged(self):
        rows = [{"coach_code": 1, "name": "Sparse Coach", "edge_count": 1}]
        driver = _mock_driver_list(rows)
        anomalies = check_coached_at_edge_counts(driver)
        assert len(anomalies) == 1
        assert anomalies[0]["type"] == "sparse"
        assert anomalies[0]["coach_code"] == 1

    def test_dense_coach_flagged(self):
        rows = [{"coach_code": 2, "name": "Dense Coach", "edge_count": 30}]
        driver = _mock_driver_list(rows)
        anomalies = check_coached_at_edge_counts(driver)
        assert len(anomalies) == 1
        assert anomalies[0]["type"] == "dense"

    def test_normal_coach_not_returned(self):
        """Driver returns empty list → no anomalies."""
        driver = _mock_driver_list([])
        anomalies = check_coached_at_edge_counts(driver)
        assert anomalies == []

    def test_both_types_in_results(self):
        rows = [
            {"coach_code": 1, "name": "Sparse", "edge_count": 1},
            {"coach_code": 2, "name": "Dense", "edge_count": 50},
        ]
        driver = _mock_driver_list(rows)
        anomalies = check_coached_at_edge_counts(driver)
        types = {a["type"] for a in anomalies}
        assert "sparse" in types
        assert "dense" in types


# ---------------------------------------------------------------------------
# check_mentored_overlap_sanity
# ---------------------------------------------------------------------------


class TestCheckMentoredOverlapSanity:
    def test_returns_flagged_edges(self):
        rows = [
            {
                "mentor_code": 10, "mentor_name": "Mentor A",
                "mentee_code": 20, "mentee_name": "Mentee B",
                "shared_years": 1,
            }
        ]
        driver = _mock_driver_list(rows)
        issues = check_mentored_overlap_sanity(driver)
        assert len(issues) == 1
        assert issues[0]["shared_years"] == 1

    def test_empty_when_no_issues(self):
        driver = _mock_driver_list([])
        issues = check_mentored_overlap_sanity(driver)
        assert issues == []

    def test_query_sent_with_min_overlap_param(self):
        driver = _mock_driver_list([])
        check_mentored_overlap_sanity(driver, min_overlap=3)
        session = driver.session().__enter__()
        call_kwargs = session.run.call_args[1]
        assert call_kwargs.get("min_overlap") == 3


# ---------------------------------------------------------------------------
# _load_ground_truth
# ---------------------------------------------------------------------------


class TestLoadGroundTruth:
    def test_keys_present(self):
        from agents.data_validation.validate import _load_ground_truth
        gt = _load_ground_truth()
        assert "tenures" in gt
        assert "mentored" in gt
        assert "not_mentored" in gt

    def test_tenures_is_list(self):
        from agents.data_validation.validate import _load_ground_truth
        gt = _load_ground_truth()
        assert isinstance(gt["tenures"], list)
        assert len(gt["tenures"]) > 0

    def test_known_tenure_present(self):
        """Kirby Smart at Alabama is a required ground-truth entry."""
        from agents.data_validation.validate import _load_ground_truth
        gt = _load_ground_truth()
        coaches = [e.get("coach", "") for e in gt["tenures"]]
        assert any("Smart" in c for c in coaches)

    def test_not_mentored_muschamp_present(self):
        """Will Muschamp / Kirby Smart must be in not_mentored."""
        from agents.data_validation.validate import _load_ground_truth
        gt = _load_ground_truth()
        pairs = [(e.get("mentor", ""), e.get("mentee", "")) for e in gt["not_mentored"]]
        assert any("Muschamp" in mentee for _, mentee in pairs)
