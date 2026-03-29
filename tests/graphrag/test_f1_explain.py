"""Tests for F1 Explain My Result — semantic vocabulary and enrichment.

Covers:
- role_display_name() in graphrag/utils.py
- get_mentee_stints() in graphrag/graph_traversal.py
- _build_explain() and _format_year_range() in graphrag/retriever.py
- ResultRow.team / ResultRow.years passthrough
"""

from unittest.mock import MagicMock

from graphrag.graph_traversal import get_mentee_stints
from graphrag.retriever import _build_explain, _format_year_range
from graphrag.synthesizer import ResultRow
from graphrag.utils import ROLE_DISPLAY_NAMES, role_display_name


# ---------------------------------------------------------------------------
# role_display_name()
# ---------------------------------------------------------------------------


class TestRoleDisplayName:
    """Tests for the semantic role name mapping."""

    def test_hc_maps_to_head_coach(self):
        assert role_display_name("HC") == "Head Coach"

    def test_oc_maps_to_offensive_coordinator(self):
        assert role_display_name("OC") == "Offensive Coordinator"

    def test_dc_maps_to_defensive_coordinator(self):
        assert role_display_name("DC") == "Defensive Coordinator"

    def test_qb_maps_to_quarterbacks_coach(self):
        assert role_display_name("QB") == "Quarterbacks Coach"

    def test_wr_maps_to_wide_receivers_coach(self):
        assert role_display_name("WR") == "Wide Receivers Coach"

    def test_none_returns_coach(self):
        assert role_display_name(None) == "Coach"

    def test_unknown_abbr_returned_as_is(self):
        assert role_display_name("ZZ") == "ZZ"

    def test_all_known_abbrs_have_mappings(self):
        """Every abbreviation in ROLE_DISPLAY_NAMES maps to a non-empty string."""
        for abbr, name in ROLE_DISPLAY_NAMES.items():
            assert isinstance(name, str)
            assert len(name) > 0
            assert role_display_name(abbr) == name


# ---------------------------------------------------------------------------
# _format_year_range()
# ---------------------------------------------------------------------------


class TestFormatYearRange:
    """Tests for the sports-notation year range formatter."""

    def test_same_century_abbreviated(self):
        assert _format_year_range(2019, 2022) == "2019–22"

    def test_different_century_full(self):
        assert _format_year_range(1999, 2003) == "1999–2003"

    def test_single_year_when_equal(self):
        assert _format_year_range(2020, 2020) == "2020"

    def test_start_only(self):
        assert _format_year_range(2020, None) == "2020"

    def test_both_none_returns_empty(self):
        assert _format_year_range(None, None) == ""

    def test_end_only_returns_empty(self):
        """When start is None but end is present, returns empty."""
        assert _format_year_range(None, 2022) == ""


# ---------------------------------------------------------------------------
# _build_explain()
# ---------------------------------------------------------------------------


class TestBuildExplain:
    """Tests for the F1 explanation builder."""

    def test_rich_explain_with_full_stint(self):
        stint = {
            "role_abbr": "OC",
            "team": "Alabama",
            "start_year": 2019,
            "end_year": 2022,
        }
        result = _build_explain("Nick Saban", "Nick Saban", 1, stint)
        assert "Offensive Coordinator at Alabama (2019–22)" in result
        assert "coached under Nick Saban" in result
        assert result.startswith("Included because:")

    def test_rich_explain_with_dc_role(self):
        stint = {
            "role_abbr": "DC",
            "team": "Georgia",
            "start_year": 2016,
            "end_year": 2020,
        }
        result = _build_explain("Nick Saban", "Nick Saban", 1, stint)
        assert "Defensive Coordinator at Georgia (2016–20)" in result

    def test_rich_explain_with_position_role(self):
        stint = {
            "role_abbr": "WR",
            "team": "LSU",
            "start_year": 2018,
            "end_year": 2019,
        }
        result = _build_explain("Nick Saban", "Kirby Smart", 2, stint)
        assert "Wide Receivers Coach at LSU (2018–19)" in result
        assert "coached under Kirby Smart" in result

    def test_rich_explain_team_only_no_role(self):
        stint = {"role_abbr": None, "team": "Alabama", "start_year": 2020, "end_year": 2022}
        result = _build_explain("Nick Saban", "Nick Saban", 1, stint)
        assert "Coach at Alabama" in result

    def test_fallback_depth_1(self):
        result = _build_explain("Nick Saban", "Nick Saban", 1, None)
        assert "direct mentee" in result
        assert "mentored by Nick Saban" in result

    def test_fallback_depth_2(self):
        result = _build_explain("Nick Saban", "Kirby Smart", 2, None)
        assert "depth-2 mentee" in result
        assert "mentored by Kirby Smart" in result

    def test_stint_with_no_years(self):
        stint = {"role_abbr": "HC", "team": "Georgia", "start_year": None, "end_year": None}
        result = _build_explain("Nick Saban", "Nick Saban", 1, stint)
        assert "Head Coach at Georgia" in result
        assert "(" not in result  # no year parens


# ---------------------------------------------------------------------------
# get_mentee_stints() — mock Neo4j driver
# ---------------------------------------------------------------------------


def _mock_driver_records(*call_results):
    """Build a mock driver whose session.run returns different results per call.

    Args:
        *call_results: Each argument is a list of dicts for one session.run call.
    """
    driver = MagicMock()
    session = MagicMock()
    session.run.side_effect = [iter(records) for records in call_results]
    driver.session.return_value.__enter__ = MagicMock(return_value=session)
    driver.session.return_value.__exit__ = MagicMock(return_value=False)
    return driver


class TestGetMenteeStints:
    """Tests for get_mentee_stints() enrichment query."""

    def test_empty_pairs_returns_empty(self):
        driver = MagicMock()
        assert get_mentee_stints([], driver) == {}
        driver.session.assert_not_called()

    def test_returns_stint_data_for_mentee(self):
        stint_records = [
            {"mentee_code": 99, "team": "Alabama", "start_year": 2008, "end_year": 2015},
        ]
        role_records = [
            {"mentee_code": 99, "role_abbr": "DC"},
        ]
        driver = _mock_driver_records(stint_records, role_records)
        result = get_mentee_stints([(99, 1457)], driver)

        assert 99 in result
        assert result[99]["team"] == "Alabama"
        assert result[99]["start_year"] == 2008
        assert result[99]["end_year"] == 2015
        assert result[99]["role_abbr"] == "DC"

    def test_multiple_mentees(self):
        stint_records = [
            {"mentee_code": 99, "team": "Alabama", "start_year": 2008, "end_year": 2015},
            {"mentee_code": 77, "team": "Alabama", "start_year": 2014, "end_year": 2016},
        ]
        role_records = [
            {"mentee_code": 99, "role_abbr": "DC"},
            {"mentee_code": 77, "role_abbr": "OC"},
        ]
        driver = _mock_driver_records(stint_records, role_records)
        result = get_mentee_stints([(99, 1457), (77, 1457)], driver)

        assert len(result) == 2
        assert result[99]["role_abbr"] == "DC"
        assert result[77]["role_abbr"] == "OC"

    def test_no_stint_found_returns_empty(self):
        driver = _mock_driver_records([])
        result = get_mentee_stints([(99, 1457)], driver)
        assert result == {}

    def test_stint_without_role_has_none_role_abbr(self):
        stint_records = [
            {"mentee_code": 99, "team": "Alabama", "start_year": 2010, "end_year": 2012},
        ]
        # No role records found
        role_records = []
        driver = _mock_driver_records(stint_records, role_records)
        result = get_mentee_stints([(99, 1457)], driver)

        assert result[99]["role_abbr"] is None


# ---------------------------------------------------------------------------
# ResultRow team/years fields
# ---------------------------------------------------------------------------


class TestResultRowTeamYears:
    """ResultRow carries team and years for graph component passthrough."""

    def test_default_team_is_none(self):
        row = ResultRow(coach_id=1, display_name="Test", depth=1, explanation="test")
        assert row.team is None

    def test_default_years_is_none(self):
        row = ResultRow(coach_id=1, display_name="Test", depth=1, explanation="test")
        assert row.years is None

    def test_team_and_years_set(self):
        row = ResultRow(
            coach_id=1,
            display_name="Test",
            depth=1,
            explanation="test",
            team="Alabama",
            years="2019–22",
        )
        assert row.team == "Alabama"
        assert row.years == "2019–22"
