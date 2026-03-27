"""Tests for graphrag/graph_traversal.py using a mock Neo4j driver."""

from unittest.mock import MagicMock

import pytest

from graphrag.graph_traversal import (
    get_best_roles,
    get_coach_tree,
    get_coaches_in_conferences,
    get_coaching_tree,
    shortest_path_between_coaches,
)


def _mock_driver(records: list[dict]) -> MagicMock:
    """Build a mock driver whose session.run returns the given record list."""
    driver = MagicMock()
    session = MagicMock()
    result = MagicMock()
    result.__iter__ = MagicMock(return_value=iter([
        MagicMock(**{"__iter__": MagicMock(return_value=iter(r.items())),
                     "keys": MagicMock(return_value=list(r.keys())),
                     "__getitem__": lambda self, k, _r=r: _r[k]})
        for r in records
    ]))

    # Simpler: session.run returns something we can iterate and call dict() on
    mock_records = []
    for r in records:
        rec = MagicMock()
        rec.__iter__ = MagicMock(return_value=iter(r.items()))
        # Make dict(record) work
        rec.data = MagicMock(return_value=r)
        mock_records.append(r)  # just use plain dicts

    session.run.return_value = iter(mock_records)
    driver.session.return_value.__enter__ = MagicMock(return_value=session)
    driver.session.return_value.__exit__ = MagicMock(return_value=False)
    return driver


def test_get_coach_tree_calls_session_run():
    """get_coach_tree should call session.run with a coach name parameter."""
    driver = MagicMock()
    session = MagicMock()
    session.run.return_value = iter([])
    driver.session.return_value.__enter__ = MagicMock(return_value=session)
    driver.session.return_value.__exit__ = MagicMock(return_value=False)

    result = get_coach_tree(driver, "Nick Saban")

    session.run.assert_called_once()
    call_kwargs = session.run.call_args
    assert "Nick Saban" in str(call_kwargs)
    assert isinstance(result, list)


def test_get_coaches_in_conferences_passes_list():
    """get_coaches_in_conferences should pass the conference list to the query."""
    driver = MagicMock()
    session = MagicMock()
    session.run.return_value = iter([])
    driver.session.return_value.__enter__ = MagicMock(return_value=session)
    driver.session.return_value.__exit__ = MagicMock(return_value=False)

    result = get_coaches_in_conferences(driver, ["SEC", "Big Ten"])

    session.run.assert_called_once()
    assert isinstance(result, list)


def test_shortest_path_calls_both_names():
    """shortest_path_between_coaches should pass both names to session.run."""
    driver = MagicMock()
    session = MagicMock()
    session.run.return_value = iter([])
    driver.session.return_value.__enter__ = MagicMock(return_value=session)
    driver.session.return_value.__exit__ = MagicMock(return_value=False)

    result = shortest_path_between_coaches(driver, "Kirby Smart", "Lincoln Riley")

    session.run.assert_called_once()
    call_str = str(session.run.call_args)
    assert "Kirby Smart" in call_str
    assert "Lincoln Riley" in call_str
    assert isinstance(result, list)


# ---------------------------------------------------------------------------
# get_coaching_tree
# ---------------------------------------------------------------------------


def _mock_driver_records(records: list[dict]) -> MagicMock:
    """Build a mock driver whose session.run yields the given plain-dict records."""
    driver = MagicMock()
    session = MagicMock()
    session.run.return_value = iter(records)
    driver.session.return_value.__enter__ = MagicMock(return_value=session)
    driver.session.return_value.__exit__ = MagicMock(return_value=False)
    return driver


def test_get_coaching_tree_hc_filter_passes_role():
    """When role_filter='HC', the role_filter param is passed to session.run."""
    driver = _mock_driver_records([])
    get_coaching_tree(coach_code=1457, role_filter="HC", max_depth=2, driver=driver)

    session = driver.session.return_value.__enter__.return_value
    call_kwargs = session.run.call_args
    assert "HC" in str(call_kwargs)


def test_get_coaching_tree_no_filter_omits_role():
    """When role_filter is None, role_filter is NOT passed to session.run."""
    driver = _mock_driver_records([])
    get_coaching_tree(coach_code=1457, role_filter=None, max_depth=2, driver=driver)

    session = driver.session.return_value.__enter__.return_value
    call_kwargs = session.run.call_args
    assert "role_filter" not in str(call_kwargs)


def test_get_coaching_tree_depth_clamped_to_4():
    """max_depth > 4 is clamped to 4; the literal '4' must appear in the query string."""
    driver = _mock_driver_records([])
    get_coaching_tree(coach_code=1457, role_filter=None, max_depth=99, driver=driver)

    session = driver.session.return_value.__enter__.return_value
    call_str = str(session.run.call_args)
    # Depth is now interpolated into the query string as a literal (not a param).
    assert "MENTORED*1..4" in call_str


def test_get_coaching_tree_returns_list():
    """get_coaching_tree always returns a list (even on empty result)."""
    driver = _mock_driver_records([])
    result = get_coaching_tree(coach_code=1457, role_filter="HC", max_depth=2, driver=driver)
    assert isinstance(result, list)


def test_get_coaching_tree_path_coaches_populated():
    """Each result dict includes a path_coaches list."""
    record = {
        "name": "Kirby Smart",
        "coach_code": 111,
        "depth": 1,
        "path_coaches": ["Nick Saban", "Kirby Smart"],
    }
    driver = _mock_driver_records([record])
    results = get_coaching_tree(coach_code=1457, role_filter="HC", max_depth=2, driver=driver)
    assert len(results) == 1
    assert results[0]["path_coaches"] == ["Nick Saban", "Kirby Smart"]


# ---------------------------------------------------------------------------
# Cycle detection — Rule 4 post-query filter in get_coaching_tree()
# ---------------------------------------------------------------------------


class TestGetCoachingTreeCycleDetection:
    """get_coaching_tree() must filter rows where the mentee IS the root coach."""

    def test_self_referential_row_excluded(self):
        """A row where coach_code equals the root is filtered out (cycle)."""
        root_code = 1457
        records = [
            # This row has the root appearing as its own mentee — must be excluded.
            {
                "name": "Nick Saban",
                "coach_code": root_code,   # same as root → cycle
                "depth": 2,
                "path_coaches": ["Nick Saban", "Kevin Steele", "Nick Saban"],
                "confidence_flag": "STANDARD",
            },
        ]
        driver = _mock_driver_records(records)
        results = get_coaching_tree(coach_code=root_code, max_depth=2, driver=driver)
        assert results == [], "Self-referential row should be filtered out"

    def test_legitimate_depth2_row_kept(self):
        """A normal depth-2 row (mentee != root) passes through unaffected."""
        root_code = 1457
        records = [
            {
                "name": "Kirby Smart",
                "coach_code": 88,           # different from root → valid
                "depth": 1,
                "path_coaches": ["Nick Saban", "Kirby Smart"],
                "confidence_flag": "STANDARD",
            },
            {
                "name": "Dan Lanning",
                "coach_code": 200,          # different from root → valid
                "depth": 2,
                "path_coaches": ["Nick Saban", "Kirby Smart", "Dan Lanning"],
                "confidence_flag": "STANDARD",
            },
        ]
        driver = _mock_driver_records(records)
        results = get_coaching_tree(coach_code=root_code, max_depth=2, driver=driver)
        assert len(results) == 2
        codes = {r["coach_code"] for r in results}
        assert 88 in codes
        assert 200 in codes
        assert root_code not in codes


# ---------------------------------------------------------------------------
# get_best_roles
# ---------------------------------------------------------------------------


class TestGetBestRoles:
    """Tests for get_best_roles() batch role lookup."""

    def test_empty_codes_returns_empty(self):
        """Empty input list returns empty dict without hitting Neo4j."""
        driver = MagicMock()
        assert get_best_roles([], driver) == {}
        driver.session.assert_not_called()

    def test_hc_role_returned(self):
        """Coach with HC role_abbr returns 'HC'."""
        records = [{"coach_code": 100, "role": "HC"}]
        driver = _mock_driver_records(records)
        result = get_best_roles([100], driver)
        assert result == {100: "HC"}

    def test_oc_role_returned(self):
        """Coach with OC as best role returns 'OC'."""
        records = [{"coach_code": 200, "role": "OC"}]
        driver = _mock_driver_records(records)
        result = get_best_roles([200], driver)
        assert result == {200: "OC"}

    def test_dc_role_returned(self):
        """Coach with DC as best role returns 'DC'."""
        records = [{"coach_code": 300, "role": "DC"}]
        driver = _mock_driver_records(records)
        result = get_best_roles([300], driver)
        assert result == {300: "DC"}

    def test_position_coach_collapsed_to_pos(self):
        """Role abbreviations outside HC/OC/DC are collapsed to 'POS'."""
        records = [{"coach_code": 400, "role": "QB"}]
        driver = _mock_driver_records(records)
        result = get_best_roles([400], driver)
        assert result == {400: "POS"}

    def test_multiple_coaches(self):
        """Multiple coach_codes return correct roles in a single batch."""
        records = [
            {"coach_code": 100, "role": "HC"},
            {"coach_code": 200, "role": "DC"},
            {"coach_code": 300, "role": "WR"},
        ]
        driver = _mock_driver_records(records)
        result = get_best_roles([100, 200, 300], driver)
        assert result == {100: "HC", 200: "DC", 300: "POS"}
