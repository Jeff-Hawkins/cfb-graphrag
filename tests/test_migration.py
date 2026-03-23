"""Tests for the AuraDB → Railway migration scripts.

Covers export_auradb and import_to_railway using mock Neo4j drivers
and temporary directories so no live database is required.
"""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock, call, patch

import pytest

from export_auradb import _run_query, _save_json, export_all
from import_to_railway import (
    import_all,
    import_coached_at_cfbd,
    import_coached_at_mcillece,
    import_coached_at_mcillece_roles,
    import_conferences,
    import_coaches,
    import_in_conference,
    import_mentored,
    import_played,
    import_played_for,
    import_players,
    import_teams,
)
from verify_railway import (
    EXPECTED_NODES,
    EXPECTED_RELS,
    check_node_counts,
    check_rel_counts,
    run_verification,
    spot_check_saban,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def mock_driver():
    """Return a mock Neo4j Driver with a session context manager."""
    driver = MagicMock()
    session = MagicMock()
    driver.session.return_value.__enter__ = MagicMock(return_value=session)
    driver.session.return_value.__exit__ = MagicMock(return_value=False)
    return driver, session


@pytest.fixture
def export_dir(tmp_path):
    """Return a temporary directory populated with minimal export JSON files."""
    d = tmp_path / "auradb_export_20260322"
    d.mkdir()

    # nodes
    (d / "nodes_Player.json").write_text(
        json.dumps([{"id": 1, "name": "Test Player", "position": "QB", "hometown": "USA"}])
    )
    (d / "nodes_Team.json").write_text(
        json.dumps([{"id": 1, "school": "Alabama", "conference": "SEC", "abbreviation": "ALA"}])
    )
    (d / "nodes_Coach.json").write_text(
        json.dumps([
            {"first_name": "Nick", "last_name": "Saban"},
            {"coach_code": "SABNIC01", "name": "Nick Saban", "coach_code": "SABNIC01"},
        ])
    )
    (d / "nodes_Conference.json").write_text(
        json.dumps([{"name": "SEC"}])
    )

    # relationships
    (d / "rels_PLAYED_FOR.json").write_text(
        json.dumps([{"player_id": 1, "year": 2020, "jersey": "1", "team_school": "Alabama"}])
    )
    (d / "rels_COACHED_AT_cfbd.json").write_text(
        json.dumps([{
            "first_name": "Nick", "last_name": "Saban", "team_school": "Alabama",
            "title": "Head Coach", "start_year": 2007, "end_year": 2023,
        }])
    )
    (d / "rels_COACHED_AT_mcillece.json").write_text(
        json.dumps([{
            "coach_code": "SABNIC01", "team_school": "Alabama",
            "year": 2015, "team_code": "ALA", "roles": ["HC"], "source": "mcillece",
        }])
    )
    (d / "rels_COACHED_AT_mcillece_roles.json").write_text(
        json.dumps([{
            "coach_code": "SABNIC01", "team_school": "Alabama",
            "rel_props": {
                "coach_code": "SABNIC01", "year": 2015, "team_code": "ALA",
                "role_abbr": "HC", "role": "Head Coach", "role_tier": "COORDINATOR",
                "is_coordinator": True, "coach_name": "Nick Saban",
                "source": "mcillece_roles",
            },
        }])
    )
    (d / "rels_PLAYED.json").write_text(
        json.dumps([{
            "home_school": "Alabama", "away_school": "Auburn",
            "rel_props": {"game_id": 9999, "home_score": 30, "away_score": 14,
                          "season": 2020, "week": 12},
        }])
    )
    (d / "rels_IN_CONFERENCE.json").write_text(
        json.dumps([{"team_school": "Alabama", "conference_name": "SEC"}])
    )
    (d / "rels_MENTORED.json").write_text(
        json.dumps([{
            "mentor_first": "Nick", "mentor_last": "Saban", "mentor_code": None,
            "mentee_first": "Kirby", "mentee_last": "Smart", "mentee_code": None,
        }])
    )

    return d


# ---------------------------------------------------------------------------
# export_auradb tests
# ---------------------------------------------------------------------------


class TestRunQuery:
    def test_returns_list_of_dicts(self, mock_driver):
        driver, session = mock_driver
        session.run.return_value = [{"props": {"id": 1, "name": "Alabama"}}]

        rows = _run_query(driver, "MATCH (n:Team) RETURN properties(n) AS props", "teams")

        assert rows == [{"props": {"id": 1, "name": "Alabama"}}]
        session.run.assert_called_once()

    def test_empty_result(self, mock_driver):
        driver, session = mock_driver
        session.run.return_value = []

        rows = _run_query(driver, "MATCH (n:Foo) RETURN n", "foo")

        assert rows == []


class TestSaveJson:
    def test_creates_file(self, tmp_path):
        data = [{"id": 1, "name": "Test"}]
        _save_json(tmp_path, "test.json", data)

        path = tmp_path / "test.json"
        assert path.exists()
        loaded = json.loads(path.read_text())
        assert loaded == data

    def test_empty_list(self, tmp_path):
        _save_json(tmp_path, "empty.json", [])
        loaded = json.loads((tmp_path / "empty.json").read_text())
        assert loaded == []


class TestExportAll:
    def test_creates_expected_files(self, tmp_path, mock_driver):
        driver, session = mock_driver
        # Return minimal results for every query
        session.run.return_value = []

        export_all(driver, tmp_path)

        expected_files = {
            "nodes_Player.json",
            "nodes_Team.json",
            "nodes_Coach.json",
            "nodes_Conference.json",
            "rels_PLAYED_FOR.json",
            "rels_COACHED_AT_cfbd.json",
            "rels_COACHED_AT_mcillece.json",
            "rels_COACHED_AT_mcillece_roles.json",
            "rels_PLAYED.json",
            "rels_IN_CONFERENCE.json",
            "rels_MENTORED.json",
        }
        actual_files = {f.name for f in tmp_path.glob("*.json")}
        assert expected_files == actual_files

    def test_returns_count_dict_with_all_keys(self, tmp_path, mock_driver):
        driver, session = mock_driver
        session.run.return_value = []

        counts = export_all(driver, tmp_path)

        assert "nodes_Player" in counts
        assert "rels_PLAYED_FOR" in counts
        assert "rels_COACHED_AT_cfbd" in counts
        assert "rels_COACHED_AT_mcillece" in counts
        assert "rels_COACHED_AT_mcillece_roles" in counts
        assert "rels_MENTORED" in counts

    def test_node_props_extracted(self, tmp_path, mock_driver):
        driver, session = mock_driver
        # First call (Player) returns data; others return empty
        session.run.side_effect = [
            [{"props": {"id": 1, "name": "TestPlayer"}}],  # Player
            [],  # Team
            [],  # Coach
            [],  # Conference
            [],  # PLAYED_FOR
            [],  # COACHED_AT cfbd
            [],  # COACHED_AT mcillece
            [],  # COACHED_AT mcillece_roles
            [],  # PLAYED
            [],  # IN_CONFERENCE
            [],  # MENTORED
        ]

        export_all(driver, tmp_path)

        players_file = tmp_path / "nodes_Player.json"
        data = json.loads(players_file.read_text())
        assert data == [{"id": 1, "name": "TestPlayer"}]


# ---------------------------------------------------------------------------
# import_to_railway tests
# ---------------------------------------------------------------------------


class TestImportTeams:
    def test_merges_teams(self, mock_driver, export_dir):
        driver, session = mock_driver
        count = import_teams(driver, export_dir)

        assert count == 1
        session.run.assert_called_once()
        query = session.run.call_args[0][0]
        assert "MERGE (t:Team" in query

    def test_empty_file(self, mock_driver, tmp_path):
        (tmp_path / "nodes_Team.json").write_text("[]")
        driver, session = mock_driver
        count = import_teams(driver, tmp_path)
        assert count == 0
        session.run.assert_not_called()


class TestImportCoaches:
    def test_splits_cfbd_and_mcillece(self, mock_driver, export_dir):
        driver, session = mock_driver
        count = import_coaches(driver, export_dir)

        # One CFBD coach (first/last) + one McIllece coach (coach_code)
        assert count == 2
        # Two separate run() calls expected (one per type)
        assert session.run.call_count == 2

    def test_cfbd_query_uses_name_key(self, mock_driver, export_dir):
        driver, session = mock_driver
        import_coaches(driver, export_dir)

        cfbd_call = session.run.call_args_list[0]
        assert "first_name" in cfbd_call[0][0]

    def test_mcillece_query_uses_coach_code(self, mock_driver, export_dir):
        driver, session = mock_driver
        import_coaches(driver, export_dir)

        mcillece_call = session.run.call_args_list[1]
        assert "coach_code" in mcillece_call[0][0]


class TestImportPlayedFor:
    def test_uses_year_as_merge_key(self, mock_driver, export_dir):
        driver, session = mock_driver
        count = import_played_for(driver, export_dir)

        assert count == 1
        query = session.run.call_args[0][0]
        assert "PLAYED_FOR {year: row.year}" in query


class TestImportCoachedAtCfbd:
    def test_uses_title_start_year_merge_key(self, mock_driver, export_dir):
        driver, session = mock_driver
        import_coached_at_cfbd(driver, export_dir)

        query = session.run.call_args[0][0]
        assert "title: row.title" in query
        assert "start_year: row.start_year" in query


class TestImportCoachedAtMcillece:
    def test_uses_coach_code_year_team_code_key(self, mock_driver, export_dir):
        driver, session = mock_driver
        import_coached_at_mcillece(driver, export_dir)

        query = session.run.call_args[0][0]
        assert "coach_code: row.coach_code" in query
        assert "year:       row.year" in query
        assert "team_code:  row.team_code" in query


class TestImportCoachedAtMcilleceRoles:
    def test_flattens_rel_props(self, mock_driver, export_dir):
        driver, session = mock_driver
        count = import_coached_at_mcillece_roles(driver, export_dir)

        assert count == 1
        # Check that rows passed to session.run have flattened keys
        rows_arg = session.run.call_args[1]["rows"]
        assert "role_abbr" in rows_arg[0]
        assert "role_tier" in rows_arg[0]

    def test_merge_key_includes_role_abbr(self, mock_driver, export_dir):
        driver, session = mock_driver
        import_coached_at_mcillece_roles(driver, export_dir)

        query = session.run.call_args[0][0]
        assert "role_abbr:  row.role_abbr" in query


class TestImportPlayed:
    def test_flattens_rel_props(self, mock_driver, export_dir):
        driver, session = mock_driver
        count = import_played(driver, export_dir)

        assert count == 1
        rows_arg = session.run.call_args[1]["rows"]
        assert "game_id" in rows_arg[0]
        assert "home_school" in rows_arg[0]

    def test_merge_key_is_game_id(self, mock_driver, export_dir):
        driver, session = mock_driver
        import_played(driver, export_dir)

        query = session.run.call_args[0][0]
        assert "game_id: row.game_id" in query


class TestImportMentored:
    def test_name_keyed_pairs_use_first_last(self, mock_driver, export_dir):
        """163 existing MENTORED edges are CFBD-sourced — match by name."""
        driver, session = mock_driver
        count = import_mentored(driver, export_dir)

        assert count == 1
        query = session.run.call_args[0][0]
        assert "first_name: row.mentor_first" in query

    def test_code_keyed_pairs_use_coach_code(self, mock_driver, tmp_path):
        """McIllece MENTORED edges should match by coach_code."""
        (tmp_path / "rels_MENTORED.json").write_text(json.dumps([{
            "mentor_first": None, "mentor_last": None, "mentor_code": "SABNIC01",
            "mentee_first": None, "mentee_last": None, "mentee_code": "SMAKIR01",
        }]))
        driver, session = mock_driver
        count = import_mentored(driver, tmp_path)

        assert count == 1
        query = session.run.call_args[0][0]
        assert "coach_code: row.mentor_code" in query

    def test_empty_mentored(self, mock_driver, tmp_path):
        (tmp_path / "rels_MENTORED.json").write_text("[]")
        driver, session = mock_driver
        count = import_mentored(driver, tmp_path)
        assert count == 0
        session.run.assert_not_called()


class TestImportAll:
    def test_calls_all_importers_in_order(self, mock_driver, export_dir):
        """import_all must load nodes before relationships."""
        driver, session = mock_driver
        counts = import_all(driver, export_dir)

        # All expected keys present
        assert "nodes_Team" in counts
        assert "nodes_Player" in counts
        assert "rels_PLAYED_FOR" in counts
        assert "rels_COACHED_AT_cfbd" in counts
        assert "rels_MENTORED" in counts

    def test_returns_count_dict(self, mock_driver, export_dir):
        driver, session = mock_driver
        counts = import_all(driver, export_dir)

        assert isinstance(counts, dict)
        assert all(isinstance(v, int) for v in counts.values())


# ---------------------------------------------------------------------------
# verify_railway tests
# ---------------------------------------------------------------------------


class TestCheckNodeCounts:
    def test_returns_label_count_dict(self, mock_driver):
        driver, session = mock_driver
        session.run.return_value = [
            {"label": "Player", "cnt": 97_765},
            {"label": "Team", "cnt": 1_862},
        ]

        counts = check_node_counts(driver)

        assert counts["Player"] == 97_765
        assert counts["Team"] == 1_862


class TestCheckRelCounts:
    def test_returns_type_count_dict(self, mock_driver):
        driver, session = mock_driver
        session.run.return_value = [
            {"rel_type": "PLAYED_FOR", "cnt": 231_540},
        ]

        counts = check_rel_counts(driver)

        assert counts["PLAYED_FOR"] == 231_540


class TestSpotCheckSaban:
    def test_returns_records(self, mock_driver):
        driver, session = mock_driver
        session.run.return_value = [
            {"name": "Nick Saban", "school": "Alabama", "year": 2015, "role": "Head Coach"}
        ]

        records = spot_check_saban(driver)

        assert len(records) == 1
        assert records[0]["school"] == "Alabama"


class TestRunVerification:
    def _make_driver_with_counts(self, node_counts, rel_counts, saban_records):
        """Build a mock driver that returns the given counts for the three queries."""
        driver = MagicMock()

        def session_factory():
            session = MagicMock()
            session.__enter__ = MagicMock(return_value=session)
            session.__exit__ = MagicMock(return_value=False)
            return session

        # Each call to driver.session() returns a fresh mock
        node_result = [{"label": k, "cnt": v} for k, v in node_counts.items()]
        rel_result = [{"rel_type": k, "cnt": v} for k, v in rel_counts.items()]
        saban_result = saban_records
        alabama_result = []

        results_cycle = iter([node_result, rel_result, saban_result, alabama_result])

        def make_session():
            s = MagicMock()
            s.__enter__ = MagicMock(return_value=s)
            s.__exit__ = MagicMock(return_value=False)
            s.run.return_value = next(results_cycle)
            return s

        driver.session.side_effect = make_session
        return driver

    def test_passes_when_counts_match(self):
        driver = self._make_driver_with_counts(
            EXPECTED_NODES,
            EXPECTED_RELS,
            [{"name": "Nick Saban", "school": "Alabama", "year": 2007, "role": "Head Coach"}],
        )

        result = run_verification(driver)

        assert result["passed"] is True
        assert result["failures"] == []

    def test_fails_on_node_count_mismatch(self):
        wrong_nodes = dict(EXPECTED_NODES)
        wrong_nodes["Player"] = 90_000  # wrong!

        driver = self._make_driver_with_counts(
            wrong_nodes,
            EXPECTED_RELS,
            [{"name": "Nick Saban", "school": "Alabama", "year": 2007, "role": "Head Coach"}],
        )

        result = run_verification(driver)

        assert result["passed"] is False
        assert any("Player" in f for f in result["failures"])

    def test_fails_on_rel_count_mismatch(self):
        wrong_rels = dict(EXPECTED_RELS)
        wrong_rels["PLAYED_FOR"] = 100  # wrong!

        driver = self._make_driver_with_counts(
            EXPECTED_NODES,
            wrong_rels,
            [{"name": "Nick Saban", "school": "Alabama", "year": 2007, "role": "Head Coach"}],
        )

        result = run_verification(driver)

        assert result["passed"] is False
        assert any("PLAYED_FOR" in f for f in result["failures"])

    def test_fails_when_saban_missing(self):
        driver = self._make_driver_with_counts(
            EXPECTED_NODES,
            EXPECTED_RELS,
            [],  # no Saban records
        )

        result = run_verification(driver)

        assert result["passed"] is False
        assert any("Saban" in f for f in result["failures"])
