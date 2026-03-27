"""Tests for graphrag/narratives.py — F4b precomputed tree narratives."""

from unittest.mock import MagicMock, patch

import pytest

from graphrag.narratives import (
    TreeMenteeRow,
    TreeSummary,
    get_coach_narrative,
    get_coach_narrative_by_name,
    get_head_coach_tree_summary,
    set_coach_narrative,
)


# ---------------------------------------------------------------------------
# Driver mock helpers
# ---------------------------------------------------------------------------


def _mock_driver_single(record: dict | None) -> MagicMock:
    """Mock driver whose session.run(...).single() returns the given dict (or None)."""
    driver = MagicMock()
    session = MagicMock()
    result = MagicMock()

    if record is None:
        result.single.return_value = None
    else:
        mock_record = MagicMock()
        mock_record.__getitem__ = lambda self, k, _r=record: _r[k]
        result.single.return_value = mock_record

    session.run.return_value = result
    driver.session.return_value.__enter__ = MagicMock(return_value=session)
    driver.session.return_value.__exit__ = MagicMock(return_value=False)
    return driver


def _mock_driver_iter(records: list[dict]) -> MagicMock:
    """Mock driver whose session.run(...) is iterable (for queries that don't use .single())."""
    driver = MagicMock()
    session = MagicMock()
    session.run.return_value = iter(records)
    driver.session.return_value.__enter__ = MagicMock(return_value=session)
    driver.session.return_value.__exit__ = MagicMock(return_value=False)
    return driver


def _make_single_session_driver(calls: list) -> MagicMock:
    """Mock driver that returns different results for sequential session.run calls.

    ``calls`` is a list of either:
    - a dict (used as single() return)
    - a list[dict] (used as iterable return)
    - None (single() returns None)
    """
    driver = MagicMock()

    sessions = []
    for call_result in calls:
        session = MagicMock()
        result = MagicMock()

        if isinstance(call_result, list):
            result.__iter__ = MagicMock(return_value=iter(call_result))
            result.single.return_value = None
            session.run.return_value = call_result  # iterable
        elif call_result is None:
            result.single.return_value = None
            session.run.return_value = result
        else:
            mock_record = MagicMock()
            mock_record.__getitem__ = lambda self, k, _r=call_result: _r[k]
            result.single.return_value = mock_record
            session.run.return_value = result

        sessions.append(session)

    call_count = [0]

    def _session_enter(self):
        idx = call_count[0]
        call_count[0] += 1
        if idx < len(sessions):
            return sessions[idx]
        return sessions[-1]

    driver.session.return_value.__enter__ = _session_enter
    driver.session.return_value.__exit__ = MagicMock(return_value=False)
    return driver


# ---------------------------------------------------------------------------
# set_coach_narrative
# ---------------------------------------------------------------------------


class TestSetCoachNarrative:
    def test_runs_set_query_and_confirms(self):
        """set_coach_narrative runs a SET query and reads the confirmed_code back."""
        driver = _mock_driver_single({"confirmed_code": 1457})
        # Should not raise.
        set_coach_narrative(coach_code=1457, narrative="Test narrative.", driver=driver)

        session = driver.session.return_value.__enter__.return_value
        session.run.assert_called_once()
        call_args = session.run.call_args
        assert call_args[1]["coach_code"] == 1457
        assert call_args[1]["narrative"] == "Test narrative."

    def test_raises_when_coach_not_found(self):
        """set_coach_narrative raises ValueError when no Coach node exists."""
        driver = _mock_driver_single(None)
        with pytest.raises(ValueError, match="No Coach node found"):
            set_coach_narrative(coach_code=9999, narrative="x", driver=driver)

    def test_narrative_updated_at_is_set(self):
        """set_coach_narrative always passes a non-empty updated_at timestamp."""
        driver = _mock_driver_single({"confirmed_code": 1457})
        set_coach_narrative(coach_code=1457, narrative="x", driver=driver)

        session = driver.session.return_value.__enter__.return_value
        call_args = session.run.call_args
        updated_at = call_args[1]["updated_at"]
        assert updated_at  # non-empty string
        assert "T" in updated_at  # ISO 8601 format


# ---------------------------------------------------------------------------
# get_coach_narrative
# ---------------------------------------------------------------------------


class TestGetCoachNarrative:
    def test_returns_narrative_when_present(self):
        """get_coach_narrative returns the stored narrative string."""
        driver = _mock_driver_single({"narrative": "Saban coached everyone."})
        result = get_coach_narrative(coach_code=1457, driver=driver)
        assert result == "Saban coached everyone."

    def test_returns_none_when_property_absent(self):
        """get_coach_narrative returns None when the narrative property is not set."""
        driver = _mock_driver_single({"narrative": None})
        result = get_coach_narrative(coach_code=1457, driver=driver)
        assert result is None

    def test_returns_none_when_coach_not_found(self):
        """get_coach_narrative returns None when no matching Coach node exists."""
        driver = _mock_driver_single(None)
        result = get_coach_narrative(coach_code=9999, driver=driver)
        assert result is None

    def test_passes_coach_code_to_query(self):
        """get_coach_narrative passes the coach_code as a query parameter."""
        driver = _mock_driver_single({"narrative": "x"})
        get_coach_narrative(coach_code=42, driver=driver)

        session = driver.session.return_value.__enter__.return_value
        call_args = session.run.call_args
        assert call_args[1]["coach_code"] == 42


# ---------------------------------------------------------------------------
# get_coach_narrative_by_name
# ---------------------------------------------------------------------------


class TestGetCoachNarrativeByName:
    def test_returns_narrative_via_cfbd_same_person(self):
        """Returns narrative resolved through CFBD → SAME_PERSON → McIllece path."""
        driver = _mock_driver_single({"narrative": "Nick Saban narrative."})
        result = get_coach_narrative_by_name("Nick Saban", driver=driver)
        assert result == "Nick Saban narrative."

    def test_returns_none_when_no_narrative(self):
        """Returns None when all narrative fields are NULL in the result."""
        driver = _mock_driver_single({"narrative": None})
        result = get_coach_narrative_by_name("Nick Saban", driver=driver)
        assert result is None

    def test_returns_none_when_record_missing(self):
        """Returns None when no matching node is found."""
        driver = _mock_driver_single(None)
        result = get_coach_narrative_by_name("Nick Saban", driver=driver)
        assert result is None

    def test_returns_none_for_single_token_name(self):
        """Returns None without hitting Neo4j when the name has only one token."""
        driver = MagicMock()
        result = get_coach_narrative_by_name("Saban", driver=driver)
        assert result is None
        driver.session.assert_not_called()

    def test_passes_first_last_and_full_name(self):
        """Passes first, last, and full_name parameters to the query."""
        driver = _mock_driver_single({"narrative": None})
        get_coach_narrative_by_name("Nick Saban", driver=driver)

        session = driver.session.return_value.__enter__.return_value
        call_args = session.run.call_args
        assert call_args[1]["first"] == "Nick"
        assert call_args[1]["last"] == "Saban"
        assert call_args[1]["full_name"] == "Nick Saban"

    def test_handles_multi_word_last_name(self):
        """Correctly splits 'Jimbo Fisher' into first='Jimbo', last='Fisher'."""
        driver = _mock_driver_single({"narrative": None})
        get_coach_narrative_by_name("Jimbo Fisher", driver=driver)

        session = driver.session.return_value.__enter__.return_value
        call_args = session.run.call_args
        assert call_args[1]["first"] == "Jimbo"
        assert call_args[1]["last"] == "Fisher"


# ---------------------------------------------------------------------------
# get_head_coach_tree_summary
# ---------------------------------------------------------------------------


class TestGetHeadCoachTreeSummary:
    def _make_driver_for_summary(
        self,
        root_name: str,
        all_rows: list[dict],
        hc_rows: list[dict],
    ) -> MagicMock:
        """Build a driver mock that serves 3 sequential session.run calls:
        1. Root name query → single record.
        2. All-mentees query → iterable.
        3. HC-only query → iterable.
        """
        driver = MagicMock()

        root_record = MagicMock()
        root_record.__getitem__ = lambda self, k: root_name if k == "name" else None

        # Session contexts are reused; we need to differentiate by call index.
        session = MagicMock()
        call_count = [0]

        def _run(*args, **kwargs):
            idx = call_count[0]
            call_count[0] += 1
            result = MagicMock()
            if idx == 0:
                # Root name query
                result.single.return_value = root_record
                result.__iter__ = MagicMock(return_value=iter([]))
            elif idx == 1:
                # All mentees
                result.__iter__ = MagicMock(return_value=iter(all_rows))
                result.single.return_value = None
            else:
                # HC mentees
                result.__iter__ = MagicMock(return_value=iter(hc_rows))
                result.single.return_value = None
            return result

        session.run.side_effect = _run
        driver.session.return_value.__enter__ = MagicMock(return_value=session)
        driver.session.return_value.__exit__ = MagicMock(return_value=False)
        return driver

    def test_returns_tree_summary_instance(self):
        driver = self._make_driver_for_summary("Nick Saban", [], [])
        result = get_head_coach_tree_summary(coach_code=1457, driver=driver)
        assert isinstance(result, TreeSummary)

    def test_root_name_populated(self):
        driver = self._make_driver_for_summary("Nick Saban", [], [])
        result = get_head_coach_tree_summary(coach_code=1457, driver=driver)
        assert result.root_name == "Nick Saban"

    def test_root_coach_code_set(self):
        driver = self._make_driver_for_summary("Nick Saban", [], [])
        result = get_head_coach_tree_summary(coach_code=1457, driver=driver)
        assert result.root_coach_code == 1457

    def test_all_mentees_populated(self):
        all_rows = [
            {"name": "Kirby Smart", "coach_code": 111, "depth": 1, "path_coaches": ["Nick Saban", "Kirby Smart"]},
            {"name": "Lane Kiffin", "coach_code": 222, "depth": 1, "path_coaches": ["Nick Saban", "Lane Kiffin"]},
        ]
        driver = self._make_driver_for_summary("Nick Saban", all_rows, [])
        result = get_head_coach_tree_summary(coach_code=1457, driver=driver)
        assert result.total_mentees == 2
        assert len(result.all_mentees) == 2

    def test_hc_mentees_populated(self):
        hc_rows = [
            {"name": "Kirby Smart", "coach_code": 111, "depth": 1, "path_coaches": ["Nick Saban", "Kirby Smart"]},
        ]
        driver = self._make_driver_for_summary("Nick Saban", hc_rows, hc_rows)
        result = get_head_coach_tree_summary(coach_code=1457, driver=driver)
        assert result.hc_mentee_count == 1
        assert result.hc_mentees[0].name == "Kirby Smart"

    def test_mentee_row_fields(self):
        all_rows = [
            {"name": "Kirby Smart", "coach_code": 111, "depth": 1, "path_coaches": ["Nick Saban", "Kirby Smart"]},
        ]
        driver = self._make_driver_for_summary("Nick Saban", all_rows, [])
        result = get_head_coach_tree_summary(coach_code=1457, driver=driver)
        row = result.all_mentees[0]
        assert isinstance(row, TreeMenteeRow)
        assert row.name == "Kirby Smart"
        assert row.coach_code == 111
        assert row.depth == 1
        assert row.path_coaches == ["Nick Saban", "Kirby Smart"]

    def test_empty_tree_returns_zero_counts(self):
        driver = self._make_driver_for_summary("Nick Saban", [], [])
        result = get_head_coach_tree_summary(coach_code=1457, driver=driver)
        assert result.total_mentees == 0
        assert result.hc_mentee_count == 0
        assert result.hc_mentees == []
        assert result.all_mentees == []

    def test_max_depth_clamped_to_4(self):
        """max_depth > 4 must be clamped; the literal '4' must appear in the query string."""
        driver = self._make_driver_for_summary("Nick Saban", [], [])
        get_head_coach_tree_summary(coach_code=1457, driver=driver, max_depth=99)

        session = driver.session.return_value.__enter__.return_value
        # The all-mentees query (call index 1) has depth interpolated into the string.
        second_call = session.run.call_args_list[1]
        call_str = str(second_call)
        assert "MENTORED*1..4" in call_str

    def test_cycle_row_excluded_from_all_mentees(self):
        """A row where coach_code equals the root is filtered from all_mentees."""
        root_code = 1457
        all_rows = [
            # Cycle: root appears as mentee at depth 2 (e.g. Saban→Steele→Saban)
            {"name": "Nick Saban", "coach_code": root_code, "depth": 2,
             "path_coaches": ["Nick Saban", "Kevin Steele", "Nick Saban"]},
            # Legitimate mentee
            {"name": "Kirby Smart", "coach_code": 111, "depth": 1,
             "path_coaches": ["Nick Saban", "Kirby Smart"]},
        ]
        driver = self._make_driver_for_summary("Nick Saban", all_rows, [])
        result = get_head_coach_tree_summary(coach_code=root_code, driver=driver)
        assert result.total_mentees == 1
        assert result.all_mentees[0].name == "Kirby Smart"

    def test_cycle_row_excluded_from_hc_mentees(self):
        """A root-looping row is also filtered from hc_mentees."""
        root_code = 1457
        hc_rows = [
            {"name": "Nick Saban", "coach_code": root_code, "depth": 2,
             "path_coaches": ["Nick Saban", "Kevin Steele", "Nick Saban"]},
        ]
        driver = self._make_driver_for_summary("Nick Saban", [], hc_rows)
        result = get_head_coach_tree_summary(coach_code=root_code, driver=driver)
        assert result.hc_mentee_count == 0
        assert result.hc_mentees == []
