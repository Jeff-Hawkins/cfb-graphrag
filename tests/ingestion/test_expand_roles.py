"""Tests for ingestion/expand_roles.py."""

import pytest

from ingestion.expand_roles import (
    COORDINATOR_FLAG_ABBRS,
    ROLE_LEGEND,
    TIER_COORDINATOR,
    TIER_POSITION_COACH,
    TIER_SUPPORT,
    TIER_UNKNOWN,
    _classify_tier,
    expand_to_role_records,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def ala_2020_staff() -> list[dict]:
    """Minimal Alabama 2020 staff matching the shape from pull_mcillece_staff."""
    return [
        {"coach_code": 1457, "team_code": 8, "year": 2020, "team": "Alabama", "coach_name": "Nick Saban",      "roles": ["HC"]},
        {"coach_code": 2369, "team_code": 8, "year": 2020, "team": "Alabama", "coach_name": "Pete Golding",    "roles": ["DC", "IB"]},
        {"coach_code": 1062, "team_code": 8, "year": 2020, "team": "Alabama", "coach_name": "Steve Sarkisian", "roles": ["OC", "QB"]},
        {"coach_code": 2182, "team_code": 8, "year": 2020, "team": "Alabama", "coach_name": "Freddie Roach",   "roles": ["DL"]},
        {"coach_code":  531, "team_code": 8, "year": 2020, "team": "Alabama", "coach_name": "Jeff Banks",      "roles": ["ST", "TE"]},
        {"coach_code":  716, "team_code": 8, "year": 2020, "team": "Alabama", "coach_name": "Kyle Flood",      "roles": ["OL"]},
        {"coach_code": 2167, "team_code": 8, "year": 2020, "team": "Alabama", "coach_name": "Charles Huff",    "roles": ["RB"]},
        {"coach_code": 1912, "team_code": 8, "year": 2020, "team": "Alabama", "coach_name": "Holman Wiggins",  "roles": ["WR"]},
    ]


# ---------------------------------------------------------------------------
# _classify_tier
# ---------------------------------------------------------------------------


class TestClassifyTier:
    def test_hc_is_coordinator(self):
        assert _classify_tier("HC") == TIER_COORDINATOR

    def test_oc_is_coordinator(self):
        assert _classify_tier("OC") == TIER_COORDINATOR

    def test_dc_is_coordinator(self):
        assert _classify_tier("DC") == TIER_COORDINATOR

    def test_pg_is_coordinator(self):
        assert _classify_tier("PG") == TIER_COORDINATOR

    def test_pd_is_coordinator(self):
        assert _classify_tier("PD") == TIER_COORDINATOR

    def test_rg_is_coordinator(self):
        assert _classify_tier("RG") == TIER_COORDINATOR

    def test_rd_is_coordinator(self):
        assert _classify_tier("RD") == TIER_COORDINATOR

    def test_qb_is_position_coach(self):
        assert _classify_tier("QB") == TIER_POSITION_COACH

    def test_wr_is_position_coach(self):
        assert _classify_tier("WR") == TIER_POSITION_COACH

    def test_ol_is_position_coach(self):
        assert _classify_tier("OL") == TIER_POSITION_COACH

    def test_lb_is_position_coach(self):
        assert _classify_tier("LB") == TIER_POSITION_COACH

    def test_fb_is_position_coach(self):
        """FB (Fullbacks) — in legend but not task spec; assigned POSITION_COACH."""
        assert _classify_tier("FB") == TIER_POSITION_COACH

    def test_or_is_position_coach(self):
        """OR (Outside Receivers) — in legend but not task spec; assigned POSITION_COACH."""
        assert _classify_tier("OR") == TIER_POSITION_COACH

    def test_st_is_support(self):
        assert _classify_tier("ST") == TIER_SUPPORT

    def test_rc_is_support(self):
        assert _classify_tier("RC") == TIER_SUPPORT

    def test_df_is_support(self):
        assert _classify_tier("DF") == TIER_SUPPORT

    def test_unknown_abbr_is_unknown(self):
        assert _classify_tier("ZZ") == TIER_UNKNOWN

    def test_ac_is_coordinator(self):
        """AC (Assistant Head Coach) is a senior role — COORDINATOR tier."""
        assert _classify_tier("AC") == TIER_COORDINATOR


# ---------------------------------------------------------------------------
# ROLE_LEGEND
# ---------------------------------------------------------------------------


class TestRoleLegend:
    def test_legend_has_expected_abbrs(self):
        """All 38 legend abbreviations (including AC) must be present."""
        expected = {
            "AC", "CB", "DB", "DC", "DE", "DF", "DL", "DT", "FB", "FG",
            "GC", "HC", "IB", "IR", "KO", "KR", "LB", "NB", "OB", "OC",
            "OF", "OL", "OR", "OT", "PD", "PG", "PK", "PR", "PT", "QB",
            "RB", "RC", "RD", "RG", "SF", "ST", "TE", "WR",
        }
        assert expected <= set(ROLE_LEGEND.keys())

    def test_ac_maps_to_assistant_head_coach(self):
        assert ROLE_LEGEND["AC"] == "Assistant Head Coach"

    def test_hc_maps_to_head_coach(self):
        assert ROLE_LEGEND["HC"] == "Head Coach"

    def test_oc_maps_to_offensive_coordinator(self):
        assert ROLE_LEGEND["OC"] == "Offensive Coordinator"

    def test_dc_maps_to_defensive_coordinator(self):
        assert ROLE_LEGEND["DC"] == "Defensive Coordinator"


# ---------------------------------------------------------------------------
# COORDINATOR_FLAG_ABBRS
# ---------------------------------------------------------------------------


def test_coordinator_flag_contains_hc_oc_dc():
    assert {"HC", "OC", "DC"} == COORDINATOR_FLAG_ABBRS


# ---------------------------------------------------------------------------
# expand_to_role_records
# ---------------------------------------------------------------------------


class TestExpandToRoleRecords:
    def test_single_role_expands_to_one_record(self):
        staff = [{"coach_code": 1, "team_code": 8, "year": 2020,
                  "team": "Alabama", "coach_name": "HC Coach", "roles": ["HC"]}]
        records, unmapped = expand_to_role_records(staff)
        assert len(records) == 1
        assert unmapped == []

    def test_two_roles_expand_to_two_records(self):
        staff = [{"coach_code": 2, "team_code": 8, "year": 2020,
                  "team": "Alabama", "coach_name": "DC/IB", "roles": ["DC", "IB"]}]
        records, _ = expand_to_role_records(staff)
        assert len(records) == 2
        abbrs = {r["role_abbr"] for r in records}
        assert abbrs == {"DC", "IB"}

    def test_alabama_2020_total_records(self, ala_2020_staff):
        """Alabama 2020 has 11 role assignments across 8 coaches."""
        records, unmapped = expand_to_role_records(ala_2020_staff)
        # Roles: HC(1) + DC,IB(2) + OC,QB(2) + DL(1) + ST,TE(2) + OL(1) + RB(1) + WR(1) = 11
        assert len(records) == 11
        assert unmapped == []

    def test_output_record_has_all_required_keys(self, ala_2020_staff):
        records, _ = expand_to_role_records(ala_2020_staff)
        required = {"coach_code", "team_code", "year", "team", "coach_name",
                    "role_abbr", "role", "role_tier", "is_coordinator"}
        for rec in records:
            assert required <= rec.keys(), f"Missing keys in {rec}"

    def test_hc_is_coordinator_tier(self, ala_2020_staff):
        records, _ = expand_to_role_records(ala_2020_staff)
        saban = next(r for r in records if r["coach_code"] == 1457)
        assert saban["role_tier"] == TIER_COORDINATOR
        assert saban["role"] == "Head Coach"

    def test_hc_has_is_coordinator_true(self, ala_2020_staff):
        records, _ = expand_to_role_records(ala_2020_staff)
        saban = next(r for r in records if r["coach_code"] == 1457)
        assert saban["is_coordinator"] is True

    def test_oc_has_is_coordinator_true(self, ala_2020_staff):
        records, _ = expand_to_role_records(ala_2020_staff)
        oc_rec = next(r for r in records if r["role_abbr"] == "OC")
        assert oc_rec["is_coordinator"] is True

    def test_position_coach_has_is_coordinator_false(self, ala_2020_staff):
        records, _ = expand_to_role_records(ala_2020_staff)
        wr_rec = next(r for r in records if r["role_abbr"] == "WR")
        assert wr_rec["is_coordinator"] is False

    def test_st_is_support_tier(self, ala_2020_staff):
        records, _ = expand_to_role_records(ala_2020_staff)
        st_rec = next(r for r in records if r["role_abbr"] == "ST")
        assert st_rec["role_tier"] == TIER_SUPPORT

    def test_ib_is_position_coach_tier(self, ala_2020_staff):
        records, _ = expand_to_role_records(ala_2020_staff)
        ib_rec = next(r for r in records if r["role_abbr"] == "IB")
        assert ib_rec["role_tier"] == TIER_POSITION_COACH

    def test_unmapped_abbr_flagged(self):
        """Unknown abbreviation appears in unmapped list and role_tier=UNKNOWN."""
        staff = [{"coach_code": 99, "team_code": 1, "year": 2010,
                  "team": "Test U", "coach_name": "Mystery", "roles": ["ZZ"]}]
        records, unmapped = expand_to_role_records(staff)
        assert "ZZ" in unmapped
        assert records[0]["role_tier"] == TIER_UNKNOWN
        assert records[0]["role"] == "ZZ"  # falls back to raw abbr

    def test_rc_question_mark_normalised_to_rc(self):
        """RC? is a dirty data variant; it must be normalised to RC."""
        staff = [{"coach_code": 55, "team_code": 3, "year": 2012,
                  "team": "Test U", "coach_name": "Recruiter", "roles": ["RC?"]}]
        records, unmapped = expand_to_role_records(staff)
        assert len(records) == 1
        assert records[0]["role_abbr"] == "RC"
        assert records[0]["role"] == "Recruiting Coordinator"
        assert records[0]["role_tier"] == TIER_SUPPORT
        assert unmapped == []  # not flagged as unknown after normalization

    def test_unmapped_abbr_data_not_dropped(self):
        """Unknown abbreviation still produces a record — no silent data loss."""
        staff = [{"coach_code": 99, "team_code": 1, "year": 2010,
                  "team": "Test U", "coach_name": "Mystery", "roles": ["ZZ"]}]
        records, unmapped = expand_to_role_records(staff)
        assert len(records) == 1
        assert "ZZ" in unmapped

    def test_empty_staff_returns_empty(self):
        records, unmapped = expand_to_role_records([])
        assert records == []
        assert unmapped == []

    def test_empty_roles_list_produces_no_records(self):
        staff = [{"coach_code": 1, "team_code": 8, "year": 2020,
                  "team": "Alabama", "coach_name": "Admin", "roles": []}]
        records, _ = expand_to_role_records(staff)
        assert records == []

    def test_year_and_codes_propagated_correctly(self, ala_2020_staff):
        records, _ = expand_to_role_records(ala_2020_staff)
        for rec in records:
            assert rec["year"] == 2020
            assert rec["team_code"] == 8
            assert rec["team"] == "Alabama"

    def test_multiple_unmapped_abbrs_sorted(self):
        staff = [{"coach_code": 1, "team_code": 1, "year": 2010,
                  "team": "X", "coach_name": "Y", "roles": ["ZZ", "AC", "XX"]}]
        _, unmapped = expand_to_role_records(staff)
        assert unmapped == sorted(unmapped)

    def test_oc_role_full_name(self, ala_2020_staff):
        records, _ = expand_to_role_records(ala_2020_staff)
        oc_rec = next(r for r in records if r["role_abbr"] == "OC")
        assert oc_rec["role"] == "Offensive Coordinator"

    def test_dc_role_full_name(self, ala_2020_staff):
        records, _ = expand_to_role_records(ala_2020_staff)
        dc_rec = next(r for r in records if r["role_abbr"] == "DC")
        assert dc_rec["role"] == "Defensive Coordinator"
