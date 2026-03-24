"""Tests for ingestion/role_constants.py.

Covers:
1. All 38 McIllece legend role codes are in ALL_ROLES
2. COORDINATOR_ROLES and ASSISTANT_ROLES are subsets of ALL_ROLES
3. validate_role returns True for known codes and False for unknown
4. No overlap between COORDINATOR_ROLES and ASSISTANT_ROLES
"""

from ingestion.expand_roles import ROLE_LEGEND
from ingestion.role_constants import (
    ALL_ROLES,
    ASSISTANT_ROLES,
    COORDINATOR_ROLES,
    validate_role,
)


# ---------------------------------------------------------------------------
# ALL_ROLES completeness
# ---------------------------------------------------------------------------


class TestAllRoles:
    """ALL_ROLES must contain every code from the McIllece legend."""

    def test_all_legend_codes_present(self) -> None:
        """Every abbreviation in ROLE_LEGEND appears in ALL_ROLES."""
        missing = set(ROLE_LEGEND.keys()) - ALL_ROLES
        assert missing == set(), f"Missing from ALL_ROLES: {missing}"

    def test_count_matches_legend(self) -> None:
        """ALL_ROLES has exactly as many entries as ROLE_LEGEND (38)."""
        assert len(ALL_ROLES) == len(ROLE_LEGEND)

    def test_no_extra_codes_beyond_legend(self) -> None:
        """ALL_ROLES contains no codes that are absent from ROLE_LEGEND."""
        extra = ALL_ROLES - set(ROLE_LEGEND.keys())
        assert extra == set(), f"Extra codes in ALL_ROLES not in legend: {extra}"

    def test_all_roles_is_frozenset(self) -> None:
        """ALL_ROLES is a frozenset (immutable — safe to share across modules)."""
        assert isinstance(ALL_ROLES, frozenset)

    def test_specific_known_roles_present(self) -> None:
        """Spot-check a handful of expected codes."""
        for code in ("HC", "OC", "DC", "AC", "QB", "WR", "ST", "RC", "DF", "OF"):
            assert code in ALL_ROLES, f"{code!r} should be in ALL_ROLES"


# ---------------------------------------------------------------------------
# COORDINATOR_ROLES
# ---------------------------------------------------------------------------


class TestCoordinatorRoles:
    """COORDINATOR_ROLES is a valid subset of ALL_ROLES with the right members."""

    def test_coordinator_roles_subset_of_all_roles(self) -> None:
        """Every code in COORDINATOR_ROLES must be in ALL_ROLES."""
        assert COORDINATOR_ROLES <= ALL_ROLES

    def test_coordinator_roles_is_frozenset(self) -> None:
        assert isinstance(COORDINATOR_ROLES, frozenset)

    def test_hc_in_coordinator_roles(self) -> None:
        assert "HC" in COORDINATOR_ROLES

    def test_oc_in_coordinator_roles(self) -> None:
        assert "OC" in COORDINATOR_ROLES

    def test_dc_in_coordinator_roles(self) -> None:
        assert "DC" in COORDINATOR_ROLES

    def test_st_in_coordinator_roles(self) -> None:
        """Special teams coordinator is included."""
        assert "ST" in COORDINATOR_ROLES

    def test_rc_in_coordinator_roles(self) -> None:
        """Recruiting coordinator is included."""
        assert "RC" in COORDINATOR_ROLES

    def test_ac_not_in_coordinator_roles(self) -> None:
        """AC (Assistant HC) is intentionally excluded from COORDINATOR_ROLES."""
        assert "AC" not in COORDINATOR_ROLES

    def test_pass_rush_coordinators_present(self) -> None:
        """PG, PD, RG, RD (pass/rush coordinator variants) are included."""
        for code in ("PG", "PD", "RG", "RD"):
            assert code in COORDINATOR_ROLES, f"{code!r} missing from COORDINATOR_ROLES"


# ---------------------------------------------------------------------------
# ASSISTANT_ROLES
# ---------------------------------------------------------------------------


class TestAssistantRoles:
    """ASSISTANT_ROLES is a valid subset of ALL_ROLES with the right members."""

    def test_assistant_roles_subset_of_all_roles(self) -> None:
        """Every code in ASSISTANT_ROLES must be in ALL_ROLES."""
        assert ASSISTANT_ROLES <= ALL_ROLES

    def test_assistant_roles_is_frozenset(self) -> None:
        assert isinstance(ASSISTANT_ROLES, frozenset)

    def test_df_in_assistant_roles(self) -> None:
        """DF (Defensive Assistant/Analyst) is in ASSISTANT_ROLES."""
        assert "DF" in ASSISTANT_ROLES

    def test_of_in_assistant_roles(self) -> None:
        """OF (Offensive Assistant/Analyst) is in ASSISTANT_ROLES."""
        assert "OF" in ASSISTANT_ROLES

    def test_hc_not_in_assistant_roles(self) -> None:
        """Head Coach is not an assistant role."""
        assert "HC" not in ASSISTANT_ROLES


# ---------------------------------------------------------------------------
# Disjoint invariant
# ---------------------------------------------------------------------------


class TestDisjointSets:
    """COORDINATOR_ROLES and ASSISTANT_ROLES must not overlap."""

    def test_no_overlap_between_coordinator_and_assistant(self) -> None:
        overlap = COORDINATOR_ROLES & ASSISTANT_ROLES
        assert overlap == set(), (
            f"COORDINATOR_ROLES and ASSISTANT_ROLES must be disjoint; "
            f"shared codes: {overlap}"
        )


# ---------------------------------------------------------------------------
# validate_role
# ---------------------------------------------------------------------------


class TestValidateRole:
    """validate_role returns True for known codes and False for unknown."""

    def test_known_codes_return_true(self) -> None:
        """Every code from the legend validates successfully."""
        for code in ROLE_LEGEND:
            assert validate_role(code) is True, f"validate_role({code!r}) should be True"

    def test_unknown_code_returns_false(self) -> None:
        assert validate_role("XX") is False

    def test_empty_string_returns_false(self) -> None:
        assert validate_role("") is False

    def test_lowercase_returns_false(self) -> None:
        """McIllece codes are uppercase — lowercase is not valid."""
        assert validate_role("hc") is False

    def test_whitespace_returns_false(self) -> None:
        assert validate_role(" HC") is False

    def test_all_roles_validate_true(self) -> None:
        """Every element of ALL_ROLES must satisfy validate_role."""
        for code in ALL_ROLES:
            assert validate_role(code) is True, f"validate_role({code!r}) returned False"


# ---------------------------------------------------------------------------
# load_staff validation integration (unit-level)
# ---------------------------------------------------------------------------


class TestLoadStaffRoleValidation:
    """load_staff logs a warning for unknown role codes but does not raise."""

    def _make_driver(self) -> object:
        from unittest.mock import MagicMock

        driver = MagicMock()
        session = MagicMock()
        driver.session.return_value.__enter__ = MagicMock(return_value=session)
        driver.session.return_value.__exit__ = MagicMock(return_value=False)
        return driver

    def test_unknown_role_logs_warning(self, caplog) -> None:
        import logging

        from loader.load_staff import load_staff

        staff = [
            {
                "coach_code": 1,
                "coach_name": "Test Coach",
                "team": "Test U",
                "team_code": "TST",
                "year": 2020,
                "roles": ["HC", "UNKNOWN_ROLE"],
            }
        ]
        driver = self._make_driver()

        with caplog.at_level(logging.WARNING, logger="loader.load_staff"):
            load_staff(driver, staff)

        assert any("UNKNOWN_ROLE" in msg for msg in caplog.messages), (
            "Expected a warning containing 'UNKNOWN_ROLE'"
        )

    def test_known_roles_no_warning(self, caplog) -> None:
        import logging

        from loader.load_staff import load_staff

        staff = [
            {
                "coach_code": 1,
                "coach_name": "Test Coach",
                "team": "Test U",
                "team_code": "TST",
                "year": 2020,
                "roles": ["HC", "OC"],
            }
        ]
        driver = self._make_driver()

        with caplog.at_level(logging.WARNING, logger="loader.load_staff"):
            load_staff(driver, staff)

        role_warnings = [m for m in caplog.messages if "Unknown role" in m]
        assert role_warnings == [], f"Unexpected role warnings: {role_warnings}"

    def test_empty_roles_no_warning(self, caplog) -> None:
        import logging

        from loader.load_staff import load_staff

        staff = [
            {
                "coach_code": 1,
                "coach_name": "Test Coach",
                "team": "Test U",
                "team_code": "TST",
                "year": 2020,
                "roles": [],
            }
        ]
        driver = self._make_driver()

        with caplog.at_level(logging.WARNING, logger="loader.load_staff"):
            load_staff(driver, staff)

        role_warnings = [m for m in caplog.messages if "Unknown role" in m]
        assert role_warnings == []
