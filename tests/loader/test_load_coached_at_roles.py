"""Tests for loader/load_coached_at_roles.py."""

from unittest.mock import MagicMock, call

import pytest

from ingestion.expand_roles import TIER_COORDINATOR, TIER_POSITION_COACH, TIER_SUPPORT
from loader.load_coached_at_roles import load_coached_at_roles


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_driver() -> MagicMock:
    """Return a mock Neo4j driver suitable for load_coached_at_roles tests."""
    driver = MagicMock()
    session = MagicMock()
    driver.session.return_value.__enter__ = MagicMock(return_value=session)
    driver.session.return_value.__exit__ = MagicMock(return_value=False)
    return driver


def _make_role_record(
    *,
    coach_code: int = 1457,
    team_code: int = 8,
    year: int = 2020,
    team: str = "Alabama",
    coach_name: str = "Nick Saban",
    role_abbr: str = "HC",
    role: str = "Head Coach",
    role_tier: str = TIER_COORDINATOR,
    is_coordinator: bool = True,
) -> dict:
    """Build a minimal role record matching expand_to_role_records output."""
    return {
        "coach_code": coach_code,
        "team_code": team_code,
        "year": year,
        "team": team,
        "coach_name": coach_name,
        "role_abbr": role_abbr,
        "role": role,
        "role_tier": role_tier,
        "is_coordinator": is_coordinator,
    }


def _get_all_queries(driver: MagicMock) -> list[str]:
    """Extract all Cypher query strings passed to session.run()."""
    session = driver.session().__enter__()
    return [
        args[0]
        for call_item in session.run.call_args_list
        if (args := call_item[0])
    ]


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestLoadCoachedAtRoles:
    def test_returns_zero_for_empty_input(self):
        driver = _make_driver()
        result = load_coached_at_roles(driver, [])
        assert result == 0

    def test_no_session_calls_for_empty_input(self):
        driver = _make_driver()
        load_coached_at_roles(driver, [])
        session = driver.session().__enter__()
        assert session.run.call_count == 0

    def test_returns_record_count(self):
        driver = _make_driver()
        records = [_make_role_record(), _make_role_record(role_abbr="OC", role="Offensive Coordinator")]
        result = load_coached_at_roles(driver, records)
        assert result == 2

    def test_merge_query_contains_coached_at(self):
        driver = _make_driver()
        records = [_make_role_record()]
        load_coached_at_roles(driver, records)
        queries = _get_all_queries(driver)
        assert any("COACHED_AT" in q for q in queries)

    def test_merge_key_includes_role_abbr(self):
        driver = _make_driver()
        records = [_make_role_record()]
        load_coached_at_roles(driver, records)
        queries = _get_all_queries(driver)
        assert any("role_abbr" in q for q in queries)

    def test_merge_key_includes_coach_code(self):
        driver = _make_driver()
        records = [_make_role_record()]
        load_coached_at_roles(driver, records)
        queries = _get_all_queries(driver)
        assert any("coach_code" in q for q in queries)

    def test_set_includes_role_tier(self):
        driver = _make_driver()
        records = [_make_role_record()]
        load_coached_at_roles(driver, records)
        queries = _get_all_queries(driver)
        assert any("role_tier" in q for q in queries)

    def test_set_includes_is_coordinator(self):
        driver = _make_driver()
        records = [_make_role_record()]
        load_coached_at_roles(driver, records)
        queries = _get_all_queries(driver)
        assert any("is_coordinator" in q for q in queries)

    def test_source_tagged_as_mcillece_roles(self):
        driver = _make_driver()
        records = [_make_role_record()]
        load_coached_at_roles(driver, records)
        queries = _get_all_queries(driver)
        assert any("mcillece_roles" in q for q in queries)

    def test_rows_sent_to_session_contain_role_abbr(self):
        driver = _make_driver()
        records = [_make_role_record(role_abbr="WR", role="Wide Receivers",
                                     role_tier=TIER_POSITION_COACH, is_coordinator=False)]
        load_coached_at_roles(driver, records)
        session = driver.session().__enter__()
        rows_arg = session.run.call_args_list[0][1]["rows"]
        assert rows_arg[0]["role_abbr"] == "WR"

    def test_rows_sent_to_session_contain_role_tier(self):
        driver = _make_driver()
        records = [_make_role_record(role_abbr="ST", role="Special Teams",
                                     role_tier=TIER_SUPPORT, is_coordinator=False)]
        load_coached_at_roles(driver, records)
        session = driver.session().__enter__()
        rows_arg = session.run.call_args_list[0][1]["rows"]
        assert rows_arg[0]["role_tier"] == TIER_SUPPORT

    def test_batching_two_sessions_for_large_input(self, monkeypatch):
        """Input larger than _BATCH_SIZE should split into multiple batches."""
        import loader.load_coached_at_roles as mod
        monkeypatch.setattr(mod, "_BATCH_SIZE", 3)

        driver = _make_driver()
        records = [_make_role_record(role_abbr=f"R{i}") for i in range(7)]
        result = load_coached_at_roles(driver, records)
        assert result == 7

        # 7 records ÷ batch_size 3 → 3 batches (3+3+1)
        session = driver.session().__enter__()
        assert session.run.call_count == 3

    def test_single_batch_for_small_input(self):
        driver = _make_driver()
        records = [_make_role_record() for _ in range(5)]
        load_coached_at_roles(driver, records)
        session = driver.session().__enter__()
        assert session.run.call_count == 1

    def test_uses_merge_not_create(self):
        driver = _make_driver()
        records = [_make_role_record()]
        load_coached_at_roles(driver, records)
        queries = _get_all_queries(driver)
        assert any("MERGE" in q for q in queries)
        assert not any("CREATE" in q for q in queries)

    def test_two_roles_same_coach_season_are_separate_records(self):
        """A coach with OC + QB in the same season must produce two separate rows."""
        driver = _make_driver()
        records = [
            _make_role_record(coach_code=1062, role_abbr="OC",
                              role="Offensive Coordinator", role_tier=TIER_COORDINATOR),
            _make_role_record(coach_code=1062, role_abbr="QB",
                              role="Quarterbacks", role_tier=TIER_POSITION_COACH,
                              is_coordinator=False),
        ]
        result = load_coached_at_roles(driver, records)
        assert result == 2

        session = driver.session().__enter__()
        rows_arg = session.run.call_args_list[0][1]["rows"]
        abbrs = {r["role_abbr"] for r in rows_arg}
        assert abbrs == {"OC", "QB"}
