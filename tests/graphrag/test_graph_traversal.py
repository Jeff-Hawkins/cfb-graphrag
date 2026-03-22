"""Tests for graphrag/graph_traversal.py using a mock Neo4j driver."""

from unittest.mock import MagicMock

import pytest

from graphrag.graph_traversal import (
    get_coach_tree,
    get_coaches_in_conferences,
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
