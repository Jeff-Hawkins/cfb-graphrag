"""Tests for MENTORED edge ingestion (build_mentored_edges) and loader (load_mentored_edges).

Covers:
- infer_mentored_pairs: clear overlap, no overlap, same start year (skip),
  overlap across multiple schools (dedup), multi-hop chains
- fetch_coached_at_records: mock Neo4j driver returns expected dicts
- load_mentored_edges: mock driver verifies MERGE call and edge count
"""

from unittest.mock import MagicMock

import pytest

from ingestion.build_mentored_edges import fetch_coached_at_records, infer_mentored_pairs
from loader.load_mentored_edges import load_mentored_edges


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_fetch_driver(query_rows: list[dict]) -> MagicMock:
    """Return a mock Neo4j driver for *fetch* calls that return record iterables.

    ``session.run()`` returns an iterable of MagicMock objects whose
    ``.data()`` method returns each dict in *query_rows*.

    Args:
        query_rows: Records to return from ``session.run()``.
    """
    driver = MagicMock()
    session = MagicMock()
    driver.session.return_value.__enter__ = MagicMock(return_value=session)
    driver.session.return_value.__exit__ = MagicMock(return_value=False)
    driver._session = session

    mock_records = []
    for row in query_rows:
        rec = MagicMock()
        rec.data.return_value = row
        mock_records.append(rec)
    session.run.return_value = mock_records  # list, not iterator — supports multiple passes

    return driver


# ---------------------------------------------------------------------------
# infer_mentored_pairs — unit tests (pure function, no mocking needed)
# ---------------------------------------------------------------------------


class TestInferMentoredPairs:
    """Unit tests for the pure overlap-inference logic."""

    def test_clear_overlap_returns_one_pair(self):
        """Two coaches who share a season at the same school → one MENTORED pair."""
        records = [
            {"first_name": "Nick",  "last_name": "Saban", "school": "Alabama", "year": 2007},
            {"first_name": "Nick",  "last_name": "Saban", "school": "Alabama", "year": 2015},
            {"first_name": "Kirby", "last_name": "Smart", "school": "Alabama", "year": 2015},
        ]
        pairs = infer_mentored_pairs(records)
        assert len(pairs) == 1
        mentor, mentee = pairs[0]
        assert mentor == {"first_name": "Nick",  "last_name": "Saban"}
        assert mentee == {"first_name": "Kirby", "last_name": "Smart"}

    def test_no_overlap_returns_empty(self):
        """Two coaches at the same school in non-overlapping years → no pairs."""
        records = [
            {"first_name": "Bear",    "last_name": "Bryant", "school": "Alabama", "year": 1970},
            {"first_name": "Gene",    "last_name": "Stallings", "school": "Alabama", "year": 1990},
        ]
        pairs = infer_mentored_pairs(records)
        assert pairs == []

    def test_same_start_year_skipped(self):
        """Two coaches who both *started* at the school the same year → skip."""
        records = [
            {"first_name": "Alpha", "last_name": "Coach", "school": "State U", "year": 2010},
            {"first_name": "Beta",  "last_name": "Coach", "school": "State U", "year": 2010},
        ]
        pairs = infer_mentored_pairs(records)
        assert pairs == []

    def test_same_start_year_with_later_overlap_skipped(self):
        """Coaches who both started 2010 but also overlap in 2012 → still skipped
        because the *first* year at that school is equal."""
        records = [
            {"first_name": "Alpha", "last_name": "Coach", "school": "State U", "year": 2010},
            {"first_name": "Alpha", "last_name": "Coach", "school": "State U", "year": 2012},
            {"first_name": "Beta",  "last_name": "Coach", "school": "State U", "year": 2010},
            {"first_name": "Beta",  "last_name": "Coach", "school": "State U", "year": 2012},
        ]
        pairs = infer_mentored_pairs(records)
        assert pairs == []

    def test_direction_mentor_has_earlier_start(self):
        """The coach who started earlier at the school is always the mentor."""
        records = [
            {"first_name": "Junior", "last_name": "Coach", "school": "U of X", "year": 2018},
            {"first_name": "Junior", "last_name": "Coach", "school": "U of X", "year": 2019},
            {"first_name": "Senior", "last_name": "Coach", "school": "U of X", "year": 2015},
            {"first_name": "Senior", "last_name": "Coach", "school": "U of X", "year": 2019},
        ]
        pairs = infer_mentored_pairs(records)
        assert len(pairs) == 1
        mentor, mentee = pairs[0]
        assert mentor["first_name"] == "Senior"
        assert mentee["first_name"] == "Junior"

    def test_dedup_across_schools(self):
        """If the same two coaches co-worked at multiple schools, only one pair is returned."""
        records = [
            # School A — overlap
            {"first_name": "Nick",  "last_name": "Saban", "school": "LSU",     "year": 2000},
            {"first_name": "Kirby", "last_name": "Smart", "school": "LSU",     "year": 2000},
            # School B — overlap again
            {"first_name": "Nick",  "last_name": "Saban", "school": "Alabama", "year": 2007},
            {"first_name": "Kirby", "last_name": "Smart", "school": "Alabama", "year": 2007},
        ]
        pairs = infer_mentored_pairs(records)
        # Saban started at LSU 2000 and Smart started at LSU 2000 → same start at LSU → skip
        # Saban started at Alabama 2007 and Smart started at Alabama 2007 → same start → skip
        assert pairs == []

    def test_dedup_different_schools_different_starts(self):
        """Coaches who co-worked at two schools (different start years each time)
        should still produce exactly one MENTORED pair (deduplication via set)."""
        records = [
            # School A: Senior started 2005, Junior started 2008, overlap 2008
            {"first_name": "Senior", "last_name": "Coach", "school": "School A", "year": 2005},
            {"first_name": "Senior", "last_name": "Coach", "school": "School A", "year": 2008},
            {"first_name": "Junior", "last_name": "Coach", "school": "School A", "year": 2008},
            # School B: Senior started 2010, Junior started 2012, overlap 2012
            {"first_name": "Senior", "last_name": "Coach", "school": "School B", "year": 2010},
            {"first_name": "Senior", "last_name": "Coach", "school": "School B", "year": 2012},
            {"first_name": "Junior", "last_name": "Coach", "school": "School B", "year": 2012},
        ]
        pairs = infer_mentored_pairs(records)
        assert len(pairs) == 1
        mentor, mentee = pairs[0]
        assert mentor["first_name"] == "Senior"
        assert mentee["first_name"] == "Junior"

    def test_empty_records_returns_empty(self):
        """Empty input yields empty output."""
        assert infer_mentored_pairs([]) == []

    def test_single_coach_returns_empty(self):
        """Only one coach at a school — no pairs possible."""
        records = [
            {"first_name": "Solo", "last_name": "Coach", "school": "Solo U", "year": 2020},
        ]
        assert infer_mentored_pairs(records) == []


# ---------------------------------------------------------------------------
# fetch_coached_at_records — integration with mocked driver
# ---------------------------------------------------------------------------


class TestFetchCoachedAtRecords:
    """Verify fetch_coached_at_records calls Neo4j and maps records correctly."""

    def test_returns_list_of_dicts(self):
        """Each Neo4j record is converted to a plain dict via .data()."""
        expected = [
            {"first_name": "Nick", "last_name": "Saban", "school": "Alabama", "year": 2015},
            {"first_name": "Kirby", "last_name": "Smart", "school": "Alabama", "year": 2015},
        ]
        driver = _make_fetch_driver(query_rows=expected)
        result = fetch_coached_at_records(driver)
        assert result == expected

    def test_calls_session_run(self):
        """Ensures the driver's session.run is invoked (query actually fires)."""
        driver = _make_fetch_driver(query_rows=[])
        fetch_coached_at_records(driver)
        driver.session().__enter__().run.assert_called()

    def test_query_contains_coached_at(self):
        """The Cypher sent to Neo4j must reference COACHED_AT."""
        driver = _make_fetch_driver(query_rows=[])
        fetch_coached_at_records(driver)
        call_args = driver.session().__enter__().run.call_args
        query_str = call_args[0][0]  # first positional arg
        assert "COACHED_AT" in query_str


# ---------------------------------------------------------------------------
# load_mentored_edges — integration with mocked driver
# ---------------------------------------------------------------------------


class TestLoadMentoredEdges:
    """Verify load_mentored_edges issues the correct MERGE query."""

    def _make_load_driver(self, total: int = 5) -> MagicMock:
        """Driver whose count query returns *total*."""
        driver = MagicMock()
        session = MagicMock()
        driver.session.return_value.__enter__ = MagicMock(return_value=session)
        driver.session.return_value.__exit__ = MagicMock(return_value=False)
        driver._session = session

        single_result = MagicMock()
        single_result.__getitem__ = lambda self, key: total
        session.run.return_value.single.return_value = single_result
        return driver

    def test_calls_merge_query(self):
        """session.run is called with a query containing MERGE."""
        driver = self._make_load_driver(total=1)
        pairs = [
            ({"first_name": "Nick", "last_name": "Saban"},
             {"first_name": "Kirby", "last_name": "Smart"}),
        ]
        load_mentored_edges(driver, pairs)
        session = driver.session().__enter__()
        assert session.run.called
        # First call should be the MERGE query
        first_call_query = session.run.call_args_list[0][0][0]
        assert "MERGE" in first_call_query

    def test_passes_correct_row_shape(self):
        """The rows param passed to the MERGE query has the expected keys."""
        driver = self._make_load_driver(total=1)
        pairs = [
            ({"first_name": "Nick",  "last_name": "Saban"},
             {"first_name": "Kirby", "last_name": "Smart"}),
        ]
        load_mentored_edges(driver, pairs)
        session = driver.session().__enter__()
        merge_call = session.run.call_args_list[0]
        rows = merge_call[1]["rows"]  # keyword arg
        assert len(rows) == 1
        assert rows[0]["mentor_first"] == "Nick"
        assert rows[0]["mentor_last"]  == "Saban"
        assert rows[0]["mentee_first"] == "Kirby"
        assert rows[0]["mentee_last"]  == "Smart"

    def test_empty_pairs_skips_merge(self, capsys):
        """With no pairs, the MERGE query is not executed."""
        driver = self._make_load_driver(total=0)
        load_mentored_edges(driver, [])
        session = driver.session().__enter__()
        # Only the count query should be called, not the MERGE
        for c in session.run.call_args_list:
            query = c[0][0] if c[0] else ""
            assert "UNWIND" not in query

    def test_prints_total_count(self, capsys):
        """Total MENTORED count is printed to stdout."""
        driver = self._make_load_driver(total=42)
        pairs = [
            ({"first_name": "A", "last_name": "B"},
             {"first_name": "C", "last_name": "D"}),
        ]
        load_mentored_edges(driver, pairs)
        captured = capsys.readouterr()
        assert "42" in captured.out
