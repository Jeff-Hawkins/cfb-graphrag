"""Tests for ingestion/flag_mentored_edges.py and the confidence_flag migration.

Covers:
1. Known reverse pair detection (McNeill/Riley) — KNOWN_REVERSE injection
2. Standard edge not incorrectly flagged — no prior HC/coord role, no known-reverse
3. Idempotency of the migration — re-running returns 0 on already-set edges
4. Report file generated and contains expected entries
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, call

import pytest

from ingestion.flag_mentored_edges import (
    CONFIDENCE_REVIEW_REVERSE,
    CONFIDENCE_STANDARD,
    _apply_flags,
    _detect_automated_flags,
    _generate_report,
    _PRIOR_ROLE_ABBRS,
    flag_suspicious_mentored_edges,
)
from ingestion.migrations.add_mentored_confidence_flag import run_migration


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

MCNEILL_CODE = 7777
RILEY_CODE = 8888


def _make_driver(*run_results: list[dict]) -> MagicMock:
    """Build a mock Neo4j driver that returns successive result lists per session.run call.

    Each element of *run_results* is the list of record dicts that one
    ``session.run()`` call should return.  The ``data()`` method on each
    record returns the dict.

    Args:
        *run_results: Positional lists — one per expected ``session.run`` call.

    Returns:
        Mock driver with ``session()`` context manager wired up.
    """
    driver = MagicMock()
    session = MagicMock()
    driver.session.return_value.__enter__ = MagicMock(return_value=session)
    driver.session.return_value.__exit__ = MagicMock(return_value=False)

    def _build_mock_records(rows: list[dict]) -> list[MagicMock]:
        records = []
        for row in rows:
            rec = MagicMock()
            rec.data.return_value = row
            records.append(rec)
        return records

    side_effects = [_build_mock_records(rows) for rows in run_results]
    session.run.side_effect = side_effects
    return driver


# ---------------------------------------------------------------------------
# 1. Known reverse pair detection (McNeill/Riley)
# ---------------------------------------------------------------------------


class TestKnownReversePairDetection:
    """KNOWN_REVERSE pairs are flagged regardless of automated detection."""

    def test_known_reverse_pair_is_flagged(self, tmp_path: Path) -> None:
        """Injecting a known-reverse pair produces a flagged edge in the result."""
        # Automated detection returns empty (no overlap data found).
        # The KNOWN_REVERSE dict is injected directly — no Neo4j name lookups.
        # _fetch_coach_names is called once to get display names for the report.
        # _apply_flags calls session.run once.
        driver = _make_driver(
            # Call 1: _detect_automated_flags → no automated flags
            [],
            # Call 2: _fetch_coach_names → returns names for McNeill + Riley
            [
                {"code": RILEY_CODE, "name": "Riley, Lincoln"},
                {"code": MCNEILL_CODE, "name": "McNeill, Ruffin"},
            ],
            # Call 3: _apply_flags → no return value needed
            [],
        )

        known_reverse = {
            (MCNEILL_CODE, RILEY_CODE): (
                "McNeill was HC at ECU before joining Riley's OU staff."
            )
        }

        flagged = flag_suspicious_mentored_edges(
            driver,
            known_reverse=known_reverse,
            report_path=tmp_path / "report.md",
        )

        assert len(flagged) == 1
        edge = flagged[0]
        assert edge["mentee_code"] == MCNEILL_CODE
        assert edge["mentor_code"] == RILEY_CODE
        assert edge.get("_known_reverse") is True

    def test_known_reverse_pair_apply_flags_called(self, tmp_path: Path) -> None:
        """_apply_flags issues a SET query containing the right coach_codes."""
        driver = _make_driver(
            [],  # detect automated
            [  # fetch names
                {"code": RILEY_CODE, "name": "Riley, Lincoln"},
                {"code": MCNEILL_CODE, "name": "McNeill, Ruffin"},
            ],
            [],  # apply flags
        )

        known_reverse = {(MCNEILL_CODE, RILEY_CODE): "rationale"}

        flag_suspicious_mentored_edges(
            driver,
            known_reverse=known_reverse,
            report_path=tmp_path / "report.md",
        )

        session = driver.session.return_value.__enter__.return_value
        # Third call is the SET query from _apply_flags
        apply_call = session.run.call_args_list[2]
        query_str: str = apply_call[0][0]
        assert "MENTORED" in query_str
        assert "confidence_flag" in query_str
        # Rows param contains correct mentor/mentee codes
        rows = apply_call[1]["rows"]
        assert len(rows) == 1
        assert rows[0]["mentor_code"] == RILEY_CODE
        assert rows[0]["mentee_code"] == MCNEILL_CODE

    def test_known_reverse_already_in_automated_is_merged(
        self, tmp_path: Path
    ) -> None:
        """When a KNOWN_REVERSE pair is also caught by automated detection,
        the result contains exactly one entry (no duplication)."""
        # Automated detection finds the Riley→McNeill edge.
        automated_row = {
            "mentor_code": RILEY_CODE,
            "mentor_name": "Riley, Lincoln",
            "mentee_code": MCNEILL_CODE,
            "mentee_name": "McNeill, Ruffin",
            "overlap_start": 2017,
            "prior_roles": [{"year": 2010, "role": "HC", "team": "East Carolina"}],
        }
        driver = _make_driver(
            [automated_row],  # detect automated
            [],               # apply flags
        )

        known_reverse = {(MCNEILL_CODE, RILEY_CODE): "rationale"}

        flagged = flag_suspicious_mentored_edges(
            driver,
            known_reverse=known_reverse,
            report_path=tmp_path / "report.md",
        )

        assert len(flagged) == 1
        edge = flagged[0]
        assert edge.get("_automated") is True
        assert edge.get("_known_reverse") is True


# ---------------------------------------------------------------------------
# 2. Standard edge not incorrectly flagged
# ---------------------------------------------------------------------------


class TestStandardEdgeNotFlagged:
    """Edges whose mentee has no prior HC/coordinator role stay unflagged."""

    def test_no_prior_role_no_flag(self, tmp_path: Path) -> None:
        """When automated detection returns empty and KNOWN_REVERSE is empty,
        no edges are flagged and _apply_flags is a no-op."""
        driver = _make_driver(
            [],  # detect automated → empty
            [],  # apply flags (no-op — called with empty list, skips session.run)
        )

        flagged = flag_suspicious_mentored_edges(
            driver,
            known_reverse={},
            report_path=tmp_path / "report.md",
        )

        assert flagged == []

    def test_apply_flags_not_called_with_empty_list(self, tmp_path: Path) -> None:
        """When there are no flagged edges, the SET query is never issued."""
        # Only one run call: the detection query.
        driver = _make_driver([])
        session = driver.session.return_value.__enter__.return_value

        flag_suspicious_mentored_edges(
            driver,
            known_reverse={},
            report_path=tmp_path / "report.md",
        )

        # Only the detection query run call should exist (index 0).
        # _apply_flags should not have issued a SET query.
        for c in session.run.call_args_list:
            query = c[0][0] if c[0] else ""
            assert "SET" not in query or "confidence_flag IS NULL" in query

    def test_detect_automated_flags_passes_coord_abbrs(self) -> None:
        """_detect_automated_flags passes the coordinator role list to the query."""
        driver = _make_driver([])
        session = driver.session.return_value.__enter__.return_value

        _detect_automated_flags(driver, _PRIOR_ROLE_ABBRS)

        call_kwargs = session.run.call_args[1]
        assert "coord_abbrs" in call_kwargs
        abbrs = call_kwargs["coord_abbrs"]
        assert "HC" in abbrs
        assert "OC" in abbrs
        assert "DC" in abbrs


# ---------------------------------------------------------------------------
# 3. Idempotency of the migration
# ---------------------------------------------------------------------------


class TestMigrationIdempotency:
    """add_mentored_confidence_flag.run_migration is safe to re-run."""

    def _make_migration_driver(self, *updated_counts: int) -> MagicMock:
        """Build a driver whose session.run().single() returns successive counts."""
        driver = MagicMock()
        session = MagicMock()
        driver.session.return_value.__enter__ = MagicMock(return_value=session)
        driver.session.return_value.__exit__ = MagicMock(return_value=False)

        records = [{"updated": n} for n in updated_counts]
        session.run.return_value.single.side_effect = records
        return driver

    def test_first_run_returns_nonzero(self) -> None:
        """First run sets flags and returns the count of updated edges."""
        driver = self._make_migration_driver(26_244)
        count = run_migration(driver)
        assert count == 26_244

    def test_second_run_returns_zero(self) -> None:
        """Re-running after all edges are flagged returns 0 (WHERE IS NULL matches nothing)."""
        driver = self._make_migration_driver(26_244, 0)

        count1 = run_migration(driver)
        count2 = run_migration(driver)

        assert count1 == 26_244
        assert count2 == 0

    def test_migration_query_uses_null_guard(self) -> None:
        """The Cypher WHERE guard must be IS NULL so existing flags are preserved."""
        driver = self._make_migration_driver(0)
        session = driver.session.return_value.__enter__.return_value

        run_migration(driver)

        query: str = session.run.call_args[0][0]
        assert "confidence_flag IS NULL" in query

    def test_migration_sets_standard_flag(self) -> None:
        """The $flag parameter passed to the query is 'STANDARD'."""
        driver = self._make_migration_driver(0)
        session = driver.session.return_value.__enter__.return_value

        run_migration(driver)

        call_kwargs = session.run.call_args[1]
        assert call_kwargs.get("flag") == CONFIDENCE_STANDARD


# ---------------------------------------------------------------------------
# 4. Report file generated and contains expected entries
# ---------------------------------------------------------------------------


class TestReportGeneration:
    """_generate_report writes a readable Markdown file with flagged edge details."""

    def _make_flagged_edge(
        self,
        *,
        mentor_code: int = RILEY_CODE,
        mentor_name: str = "Riley, Lincoln",
        mentee_code: int = MCNEILL_CODE,
        mentee_name: str = "McNeill, Ruffin",
        overlap_start: int = 2017,
        prior_roles: list[dict] | None = None,
        known_reverse: bool = True,
        automated: bool = False,
    ) -> dict:
        edge: dict = {
            "mentor_code": mentor_code,
            "mentor_name": mentor_name,
            "mentee_code": mentee_code,
            "mentee_name": mentee_name,
            "overlap_start": overlap_start,
            "prior_roles": prior_roles
            or [{"year": 2010, "role": "HC", "team": "East Carolina"}],
            "_automated": automated,
            "_known_reverse": known_reverse,
        }
        return edge

    def test_report_file_created(self, tmp_path: Path) -> None:
        """Report file is created at the specified path."""
        report_path = tmp_path / "reports" / "mentored_flag_report.md"
        edge = self._make_flagged_edge()
        known = {(MCNEILL_CODE, RILEY_CODE): "McNeill was HC at ECU first."}

        _generate_report([edge], known, report_path)

        assert report_path.exists()

    def test_report_contains_mentee_name(self, tmp_path: Path) -> None:
        """Report includes the mentee's name."""
        report_path = tmp_path / "report.md"
        edge = self._make_flagged_edge()
        known = {(MCNEILL_CODE, RILEY_CODE): "rationale text"}

        _generate_report([edge], known, report_path)

        content = report_path.read_text()
        assert "McNeill" in content

    def test_report_contains_mentor_name(self, tmp_path: Path) -> None:
        """Report includes the mentor's name."""
        report_path = tmp_path / "report.md"
        edge = self._make_flagged_edge()
        known = {(MCNEILL_CODE, RILEY_CODE): "rationale text"}

        _generate_report([edge], known, report_path)

        content = report_path.read_text()
        assert "Riley" in content

    def test_report_contains_prior_role(self, tmp_path: Path) -> None:
        """Report lists the mentee's prior HC/coordinator role."""
        report_path = tmp_path / "report.md"
        edge = self._make_flagged_edge(
            prior_roles=[{"year": 2010, "role": "HC", "team": "East Carolina"}]
        )
        known = {(MCNEILL_CODE, RILEY_CODE): ""}

        _generate_report([edge], known, report_path)

        content = report_path.read_text()
        assert "HC" in content
        assert "East Carolina" in content

    def test_report_contains_known_reverse_rationale(self, tmp_path: Path) -> None:
        """Report includes the KNOWN_REVERSE rationale string."""
        report_path = tmp_path / "report.md"
        rationale = "McNeill was HC at ECU before joining Riley's OU staff."
        edge = self._make_flagged_edge()
        known = {(MCNEILL_CODE, RILEY_CODE): rationale}

        _generate_report([edge], known, report_path)

        content = report_path.read_text()
        assert "McNeill was HC at ECU" in content

    def test_report_notes_fcs_filter_not_applied(self, tmp_path: Path) -> None:
        """Report explicitly notes that the FCS division filter was not applied."""
        report_path = tmp_path / "report.md"
        _generate_report([], {}, report_path)

        content = report_path.read_text()
        assert "FCS" in content
        assert "NOT APPLIED" in content

    def test_report_empty_edges_section(self, tmp_path: Path) -> None:
        """When no edges are flagged, the report still renders cleanly."""
        report_path = tmp_path / "report.md"
        _generate_report([], {}, report_path)

        content = report_path.read_text()
        assert "# MENTORED Edge Confidence Flag Report" in content
        assert "_No edges flagged._" in content

    def test_flag_suspicious_mentored_edges_writes_report(
        self, tmp_path: Path
    ) -> None:
        """flag_suspicious_mentored_edges creates the report at the given path."""
        driver = _make_driver([], [])  # detection + apply_flags (empty)

        report_path = tmp_path / "mentored_flag_report.md"
        flag_suspicious_mentored_edges(
            driver,
            known_reverse={},
            report_path=report_path,
        )

        assert report_path.exists()


# ---------------------------------------------------------------------------
# 5. Synthesizer confidence_flag passthrough (unit tests on explanation helper)
# ---------------------------------------------------------------------------


class TestSynthesizerConfidenceFlag:
    """_explain_coaching_tree_row appends the flag note for non-STANDARD edges."""

    def test_standard_flag_no_note(self) -> None:
        from graphrag.synthesizer import _explain_coaching_tree_row

        row = {
            "depth": 1,
            "path_coaches": ["Nick Saban", "Kirby Smart"],
            "confidence_flag": "STANDARD",
        }
        explanation = _explain_coaching_tree_row(row, "Nick Saban")
        assert "[relationship direction flagged for review]" not in explanation

    def test_none_flag_no_note(self) -> None:
        from graphrag.synthesizer import _explain_coaching_tree_row

        row = {"depth": 1, "path_coaches": ["Nick Saban", "Kirby Smart"]}
        explanation = _explain_coaching_tree_row(row, "Nick Saban")
        assert "[relationship direction flagged for review]" not in explanation

    def test_review_reverse_appends_note(self) -> None:
        from graphrag.synthesizer import _explain_coaching_tree_row

        row = {
            "depth": 1,
            "path_coaches": ["Lincoln Riley", "Ruffin McNeill"],
            "confidence_flag": "REVIEW_REVERSE",
        }
        explanation = _explain_coaching_tree_row(row, "Lincoln Riley")
        assert "[relationship direction flagged for review]" in explanation

    def test_review_reverse_with_enriched_row(self) -> None:
        """Flag note appended even when COACHED_AT metadata produces the rich format."""
        from graphrag.synthesizer import _explain_coaching_tree_row

        row = {
            "depth": 1,
            "path_coaches": ["Lincoln Riley", "Ruffin McNeill"],
            "role": "HC",
            "team": "Oklahoma",
            "start_year": 2017,
            "end_year": 2021,
            "confidence_flag": "REVIEW_REVERSE",
        }
        explanation = _explain_coaching_tree_row(row, "Lincoln Riley")
        assert "Head Coach at Oklahoma" in explanation
        assert "coached under Lincoln Riley" in explanation
        assert "[relationship direction flagged for review]" in explanation

    def test_result_row_carries_confidence_flag(self) -> None:
        """_rows_from_coaching_tree passes confidence_flag into each ResultRow."""
        from graphrag.synthesizer import _rows_from_coaching_tree

        rows = [
            {
                "name": "Ruffin McNeill",
                "coach_code": MCNEILL_CODE,
                "depth": 1,
                "path_coaches": ["Lincoln Riley", "Ruffin McNeill"],
                "confidence_flag": "REVIEW_REVERSE",
            }
        ]
        result_rows = _rows_from_coaching_tree(rows, "Lincoln Riley")
        assert len(result_rows) == 1
        assert result_rows[0].confidence_flag == "REVIEW_REVERSE"
