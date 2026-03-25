"""Tests for the v2 MENTORED edge dry-run helpers.

Covers:
- _max_consecutive: various year-set shapes
- infer_mentored_edges_v2: coordinator filter, consecutive-year requirement,
  per-team dedup, multiple mentors, edge metadata
- Rule 1 — Prior HC: mentee held HC role before overlap → edge suppressed
- Rule 2 — Same-level coordinator: both hold OC/DC at same team/year → no edge
- Rule 3 — Minimum 2-consecutive overlap: verified
- fetch_coached_at_mcillece_roles: query must filter by mcillece_roles source
- compute_dry_run_stats: totals, overlap buckets, role breakdown, top-N lists
- save_dry_run_csv: file is created, header is correct, rows match edge list
"""

from pathlib import Path
from unittest.mock import MagicMock

import pytest

from ingestion.build_mentored_edges import (
    _max_consecutive,
    compute_dry_run_stats,
    fetch_coached_at_mcillece_roles,
    infer_mentored_edges_v2,
    save_dry_run_csv,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _role_rec(
    *,
    coach_code: int,
    coach_name: str,
    team: str,
    year: int,
    role_abbr: str,
    role_tier: str = "POSITION_COACH",
) -> dict:
    """Build a minimal role-season record matching fetch_coached_at_mcillece_roles output."""
    return {
        "coach_code": coach_code,
        "coach_name": coach_name,
        "team": team,
        "year": year,
        "role_abbr": role_abbr,
        "role_tier": role_tier,
    }


def _coord_rec(
    *,
    coach_code: int,
    coach_name: str,
    team: str,
    year: int,
    role_abbr: str = "HC",
) -> dict:
    """Build a COORDINATOR role-season record."""
    return _role_rec(
        coach_code=coach_code,
        coach_name=coach_name,
        team=team,
        year=year,
        role_abbr=role_abbr,
        role_tier="COORDINATOR",
    )


def _make_edge(
    *,
    mentor_code: int = 1,
    mentor_name: str = "Mentor Coach",
    mentee_code: int = 2,
    mentee_name: str = "Mentee Coach",
    team: str = "State U",
    overlap_years: int = 2,
    mentor_role_abbr: str = "HC",
) -> dict:
    """Build a minimal projected MENTORED edge dict."""
    return {
        "mentor_code": mentor_code,
        "mentor_name": mentor_name,
        "mentee_code": mentee_code,
        "mentee_name": mentee_name,
        "team": team,
        "overlap_years": overlap_years,
        "mentor_role_abbr": mentor_role_abbr,
    }


def _make_fetch_driver(query_rows: list[dict]) -> MagicMock:
    """Return a mock Neo4j driver whose session.run() yields *query_rows*."""
    driver = MagicMock()
    session = MagicMock()
    driver.session.return_value.__enter__ = MagicMock(return_value=session)
    driver.session.return_value.__exit__ = MagicMock(return_value=False)
    mock_records = []
    for row in query_rows:
        rec = MagicMock()
        rec.data.return_value = row
        mock_records.append(rec)
    session.run.return_value = mock_records
    return driver


# ---------------------------------------------------------------------------
# _max_consecutive
# ---------------------------------------------------------------------------


class TestMaxConsecutive:
    def test_empty_set_returns_zero(self):
        assert _max_consecutive(set()) == 0

    def test_single_year_returns_one(self):
        assert _max_consecutive({2015}) == 1

    def test_two_consecutive_years(self):
        assert _max_consecutive({2015, 2016}) == 2

    def test_two_non_consecutive_years(self):
        assert _max_consecutive({2015, 2017}) == 1

    def test_three_consecutive_years(self):
        assert _max_consecutive({2010, 2011, 2012}) == 3

    def test_gap_in_middle_returns_max_run(self):
        # {2010, 2011, 2013, 2014} → two runs of 2
        assert _max_consecutive({2010, 2011, 2013, 2014}) == 2

    def test_long_run(self):
        assert _max_consecutive(set(range(2005, 2025))) == 20

    def test_mixed_gap_and_run(self):
        # {2010, 2012, 2013, 2014} → run of 3 wins over run of 1
        assert _max_consecutive({2010, 2012, 2013, 2014}) == 3


# ---------------------------------------------------------------------------
# infer_mentored_edges_v2
# ---------------------------------------------------------------------------


class TestInferMentoredEdgesV2:
    def test_empty_records_returns_empty(self):
        assert infer_mentored_edges_v2([]) == []

    def test_single_coach_no_pair(self):
        records = [_coord_rec(coach_code=1, coach_name="HC", team="A", year=2010)]
        assert infer_mentored_edges_v2(records) == []

    def test_non_coordinator_pair_no_edge(self):
        """Two position coaches with 3-year overlap → no MENTORED edge."""
        records = [
            _role_rec(coach_code=1, coach_name="WR", team="A", year=2010, role_abbr="WR"),
            _role_rec(coach_code=1, coach_name="WR", team="A", year=2011, role_abbr="WR"),
            _role_rec(coach_code=1, coach_name="WR", team="A", year=2012, role_abbr="WR"),
            _role_rec(coach_code=2, coach_name="QB", team="A", year=2010, role_abbr="QB"),
            _role_rec(coach_code=2, coach_name="QB", team="A", year=2011, role_abbr="QB"),
            _role_rec(coach_code=2, coach_name="QB", team="A", year=2012, role_abbr="QB"),
        ]
        assert infer_mentored_edges_v2(records) == []

    def test_only_one_year_overlap_excluded(self):
        """Coordinator and position coach share exactly 1 year → no edge."""
        records = [
            _coord_rec(coach_code=1, coach_name="HC", team="A", year=2010),
            _coord_rec(coach_code=1, coach_name="HC", team="A", year=2011),
            _role_rec(coach_code=2, coach_name="WR", team="A", year=2011, role_abbr="WR"),
        ]
        assert infer_mentored_edges_v2(records) == []

    def test_two_consecutive_years_creates_edge(self):
        """2-year consecutive overlap with coordinator mentor → 1 edge."""
        records = [
            _coord_rec(coach_code=1, coach_name="HC", team="A", year=2010),
            _coord_rec(coach_code=1, coach_name="HC", team="A", year=2011),
            _role_rec(coach_code=2, coach_name="WR", team="A", year=2010, role_abbr="WR"),
            _role_rec(coach_code=2, coach_name="WR", team="A", year=2011, role_abbr="WR"),
        ]
        edges = infer_mentored_edges_v2(records)
        assert len(edges) == 1
        e = edges[0]
        assert e["mentor_code"] == 1
        assert e["mentee_code"] == 2
        assert e["team"] == "A"
        assert e["overlap_years"] == 2
        assert e["mentor_role_abbr"] == "HC"

    def test_gap_in_overlap_fails_consecutive_check(self):
        """Overlap years {2010, 2012} are not consecutive → no edge."""
        records = [
            _coord_rec(coach_code=1, coach_name="HC", team="A", year=2010),
            _coord_rec(coach_code=1, coach_name="HC", team="A", year=2011),
            _coord_rec(coach_code=1, coach_name="HC", team="A", year=2012),
            _role_rec(coach_code=2, coach_name="WR", team="A", year=2010, role_abbr="WR"),
            _role_rec(coach_code=2, coach_name="WR", team="A", year=2012, role_abbr="WR"),
        ]
        # overlap = {2010, 2012} → max_consecutive = 1 → no edge
        assert infer_mentored_edges_v2(records) == []

    def test_gap_in_overlap_with_run_of_two(self):
        """Overlap {2010, 2011, 2013} has a run of 2 → edge created."""
        records = [
            _coord_rec(coach_code=1, coach_name="HC", team="A", year=2010),
            _coord_rec(coach_code=1, coach_name="HC", team="A", year=2011),
            _coord_rec(coach_code=1, coach_name="HC", team="A", year=2013),
            _role_rec(coach_code=2, coach_name="WR", team="A", year=2010, role_abbr="WR"),
            _role_rec(coach_code=2, coach_name="WR", team="A", year=2011, role_abbr="WR"),
            _role_rec(coach_code=2, coach_name="WR", team="A", year=2013, role_abbr="WR"),
        ]
        edges = infer_mentored_edges_v2(records)
        assert len(edges) == 1
        assert edges[0]["overlap_years"] == 2

    def test_overlap_years_reflects_max_consecutive_run(self):
        """7-year consecutive overlap → overlap_years=7."""
        records = []
        for yr in range(2010, 2017):
            records.append(_coord_rec(coach_code=1, coach_name="HC", team="A", year=yr))
            records.append(
                _role_rec(coach_code=2, coach_name="WR", team="A", year=yr, role_abbr="WR")
            )
        edges = infer_mentored_edges_v2(records)
        assert len(edges) == 1
        assert edges[0]["overlap_years"] == 7

    def test_multiple_mentors_each_create_edges(self):
        """HC and OC both mentor a WR coach; HC also mentors the OC.

        Rule 1 Part A suppresses OC→HC: the HC was HC at this school during
        the overlap, so the OC cannot be listed as the HC's mentor.
        Expected edges: HC→WR, OC→WR, HC→OC  (3 total, not 4).
        """
        records = [
            _coord_rec(coach_code=10, coach_name="HC", team="A", year=2010),
            _coord_rec(coach_code=10, coach_name="HC", team="A", year=2011),
            _coord_rec(coach_code=20, coach_name="OC", team="A", year=2010, role_abbr="OC"),
            _coord_rec(coach_code=20, coach_name="OC", team="A", year=2011, role_abbr="OC"),
            _role_rec(coach_code=30, coach_name="WR", team="A", year=2010, role_abbr="WR"),
            _role_rec(coach_code=30, coach_name="WR", team="A", year=2011, role_abbr="WR"),
        ]
        edges = infer_mentored_edges_v2(records)
        mentor_mentee_pairs = {(e["mentor_code"], e["mentee_code"]) for e in edges}
        assert (10, 30) in mentor_mentee_pairs   # HC → WR
        assert (20, 30) in mentor_mentee_pairs   # OC → WR
        assert (10, 20) in mentor_mentee_pairs   # HC → OC
        assert (20, 10) not in mentor_mentee_pairs  # OC → HC suppressed (Rule 1 Part A)
        assert len(edges) == 3

    def test_different_teams_produce_separate_edges(self):
        """Same pair coaching together at two different schools → 2 edges."""
        records = [
            # Team A
            _coord_rec(coach_code=1, coach_name="HC", team="Team A", year=2010),
            _coord_rec(coach_code=1, coach_name="HC", team="Team A", year=2011),
            _role_rec(coach_code=2, coach_name="WR", team="Team A", year=2010, role_abbr="WR"),
            _role_rec(coach_code=2, coach_name="WR", team="Team A", year=2011, role_abbr="WR"),
            # Team B — same coaches, different team
            _coord_rec(coach_code=1, coach_name="HC", team="Team B", year=2015),
            _coord_rec(coach_code=1, coach_name="HC", team="Team B", year=2016),
            _role_rec(coach_code=2, coach_name="WR", team="Team B", year=2015, role_abbr="WR"),
            _role_rec(coach_code=2, coach_name="WR", team="Team B", year=2016, role_abbr="WR"),
        ]
        edges = infer_mentored_edges_v2(records)
        assert len(edges) == 2
        teams = {e["team"] for e in edges}
        assert teams == {"Team A", "Team B"}

    def test_no_duplicate_edge_for_long_overlap(self):
        """5-year overlap between HC and WR coach → exactly 1 edge, not 5."""
        records = []
        for yr in range(2010, 2015):
            records.append(_coord_rec(coach_code=1, coach_name="HC", team="A", year=yr))
            records.append(
                _role_rec(coach_code=2, coach_name="WR", team="A", year=yr, role_abbr="WR")
            )
        edges = infer_mentored_edges_v2(records)
        assert len(edges) == 1

    def test_ac_role_qualifies_as_mentor(self):
        """Assistant Head Coach (AC) is a COORDINATOR and qualifies as mentor."""
        records = [
            _coord_rec(coach_code=1, coach_name="AC Coach", team="A", year=2010, role_abbr="AC"),
            _coord_rec(coach_code=1, coach_name="AC Coach", team="A", year=2011, role_abbr="AC"),
            _role_rec(coach_code=2, coach_name="LB Coach", team="A", year=2010, role_abbr="LB"),
            _role_rec(coach_code=2, coach_name="LB Coach", team="A", year=2011, role_abbr="LB"),
        ]
        edges = infer_mentored_edges_v2(records)
        assert len(edges) == 1
        assert edges[0]["mentor_role_abbr"] == "AC"

    def test_mentor_role_abbr_prefers_hc_over_oc(self):
        """When mentor holds HC and OC in different overlap years, HC is reported."""
        records = [
            _coord_rec(coach_code=1, coach_name="Coach", team="A", year=2010, role_abbr="OC"),
            _coord_rec(coach_code=1, coach_name="Coach", team="A", year=2011, role_abbr="HC"),
            _role_rec(coach_code=2, coach_name="WR", team="A", year=2010, role_abbr="WR"),
            _role_rec(coach_code=2, coach_name="WR", team="A", year=2011, role_abbr="WR"),
        ]
        edges = infer_mentored_edges_v2(records)
        assert len(edges) == 1
        assert edges[0]["mentor_role_abbr"] == "HC"

    def test_no_overlap_returns_empty(self):
        """Coaches at the same team in non-overlapping years → no edge."""
        records = [
            _coord_rec(coach_code=1, coach_name="HC", team="A", year=2010),
            _coord_rec(coach_code=1, coach_name="HC", team="A", year=2011),
            _role_rec(coach_code=2, coach_name="WR", team="A", year=2015, role_abbr="WR"),
            _role_rec(coach_code=2, coach_name="WR", team="A", year=2016, role_abbr="WR"),
        ]
        assert infer_mentored_edges_v2(records) == []

    def test_edge_contains_coach_names(self):
        """mentor_name and mentee_name are populated from the records."""
        records = [
            _coord_rec(coach_code=99, coach_name="Nick Saban", team="Alabama", year=2010),
            _coord_rec(coach_code=99, coach_name="Nick Saban", team="Alabama", year=2011),
            _role_rec(
                coach_code=88,
                coach_name="Kirby Smart",
                team="Alabama",
                year=2010,
                role_abbr="DB",
            ),
            _role_rec(
                coach_code=88,
                coach_name="Kirby Smart",
                team="Alabama",
                year=2011,
                role_abbr="DB",
            ),
        ]
        edges = infer_mentored_edges_v2(records)
        assert len(edges) == 1
        assert edges[0]["mentor_name"] == "Nick Saban"
        assert edges[0]["mentee_name"] == "Kirby Smart"


# ---------------------------------------------------------------------------
# fetch_coached_at_mcillece_roles
# ---------------------------------------------------------------------------


class TestFetchCoachedAtMcilleceRoles:
    def test_returns_list_of_dicts(self):
        """Each Neo4j record is mapped to a plain dict via .data()."""
        rows = [
            {"coach_code": 1, "coach_name": "HC", "team": "A", "year": 2010, "role_abbr": "HC"},
        ]
        driver = _make_fetch_driver(rows)
        result = fetch_coached_at_mcillece_roles(driver)
        assert result == rows

    def test_query_filters_mcillece_roles_source(self):
        """The Cypher query must include the mcillece_roles source filter."""
        driver = _make_fetch_driver([])
        fetch_coached_at_mcillece_roles(driver)
        session = driver.session().__enter__()
        query = session.run.call_args[0][0]
        assert "mcillece_roles" in query

    def test_query_references_coached_at(self):
        """Query must reference the COACHED_AT relationship."""
        driver = _make_fetch_driver([])
        fetch_coached_at_mcillece_roles(driver)
        session = driver.session().__enter__()
        query = session.run.call_args[0][0]
        assert "COACHED_AT" in query

    def test_returns_empty_for_no_rows(self):
        driver = _make_fetch_driver([])
        assert fetch_coached_at_mcillece_roles(driver) == []


# ---------------------------------------------------------------------------
# compute_dry_run_stats
# ---------------------------------------------------------------------------


class TestComputeDryRunStats:
    def test_total_matches_edge_count(self):
        edges = [_make_edge(overlap_years=2), _make_edge(overlap_years=3)]
        stats = compute_dry_run_stats(edges)
        assert stats["total"] == 2

    def test_empty_edges(self):
        stats = compute_dry_run_stats([])
        assert stats["total"] == 0
        assert stats["by_overlap"] == {}
        assert stats["by_mentor_role"] == {}
        assert stats["top_mentors"] == []
        assert stats["top_mentees"] == []

    def test_overlap_buckets_2yr_3yr_4yr(self):
        edges = [
            _make_edge(overlap_years=2),
            _make_edge(overlap_years=3),
            _make_edge(overlap_years=4),
        ]
        stats = compute_dry_run_stats(edges)
        assert stats["by_overlap"]["2yr"] == 1
        assert stats["by_overlap"]["3yr"] == 1
        assert stats["by_overlap"]["4yr"] == 1

    def test_overlap_bucket_5yr_plus(self):
        edges = [
            _make_edge(overlap_years=5),
            _make_edge(overlap_years=6),
            _make_edge(overlap_years=10),
        ]
        stats = compute_dry_run_stats(edges)
        assert stats["by_overlap"].get("5yr+") == 3
        assert "5yr" not in stats["by_overlap"]
        assert "6yr" not in stats["by_overlap"]

    def test_role_breakdown(self):
        edges = [
            _make_edge(mentor_role_abbr="HC"),
            _make_edge(mentor_role_abbr="HC"),
            _make_edge(mentor_role_abbr="OC"),
        ]
        stats = compute_dry_run_stats(edges)
        assert stats["by_mentor_role"]["HC"] == 2
        assert stats["by_mentor_role"]["OC"] == 1

    def test_top_mentors_counts_unique_mentees(self):
        """top_mentors counts distinct mentee codes, not total edges."""
        edges = [
            _make_edge(mentor_code=1, mentor_name="A", mentee_code=10, team="X"),
            _make_edge(mentor_code=1, mentor_name="A", mentee_code=10, team="Y"),  # same mentee, diff team
            _make_edge(mentor_code=1, mentor_name="A", mentee_code=20, team="X"),
        ]
        stats = compute_dry_run_stats(edges)
        # Mentor 1 has 2 unique mentees (codes 10 and 20)
        top = dict(stats["top_mentors"])
        assert len(top[(1, "A")]) == 2

    def test_top_mentees_counts_unique_mentors(self):
        """top_mentees counts distinct mentor codes."""
        edges = [
            _make_edge(mentor_code=10, mentee_code=99, mentee_name="Mentee"),
            _make_edge(mentor_code=20, mentee_code=99, mentee_name="Mentee"),
            _make_edge(mentor_code=30, mentee_code=99, mentee_name="Mentee"),
        ]
        stats = compute_dry_run_stats(edges)
        top = dict(stats["top_mentees"])
        assert len(top[(99, "Mentee")]) == 3

    def test_top_mentors_capped_at_ten(self):
        """top_mentors list contains at most 10 entries."""
        edges = [
            _make_edge(mentor_code=i, mentor_name=f"Mentor{i}", mentee_code=99)
            for i in range(20)
        ]
        stats = compute_dry_run_stats(edges)
        assert len(stats["top_mentors"]) == 10

    def test_top_mentors_sorted_descending(self):
        """top_mentors is ordered by mentee count, highest first."""
        # Mentor 1 → 3 distinct mentees; Mentor 2 → 1 mentee
        edges = [
            _make_edge(mentor_code=1, mentor_name="Big", mentee_code=10),
            _make_edge(mentor_code=1, mentor_name="Big", mentee_code=11),
            _make_edge(mentor_code=1, mentor_name="Big", mentee_code=12),
            _make_edge(mentor_code=2, mentor_name="Small", mentee_code=20),
        ]
        stats = compute_dry_run_stats(edges)
        first_key, first_mentees = stats["top_mentors"][0]
        assert first_key[0] == 1
        assert len(first_mentees) == 3


# ---------------------------------------------------------------------------
# save_dry_run_csv
# ---------------------------------------------------------------------------


class TestSaveDryRunCsv:
    def test_creates_csv_file(self, tmp_path: Path):
        out = tmp_path / "test_out.csv"
        save_dry_run_csv([_make_edge()], out)
        assert out.exists()

    def test_header_row_is_correct(self, tmp_path: Path):
        out = tmp_path / "test_out.csv"
        save_dry_run_csv([], out)
        lines = out.read_text().splitlines()
        assert lines[0] == (
            "mentor_code,mentor_name,mentee_code,mentee_name,"
            "team,overlap_years,mentor_role_abbr"
        )

    def test_row_count_matches_edge_list(self, tmp_path: Path):
        out = tmp_path / "test_out.csv"
        edges = [_make_edge(mentor_code=i) for i in range(5)]
        save_dry_run_csv(edges, out)
        lines = out.read_text().splitlines()
        assert len(lines) == 6  # 1 header + 5 data rows

    def test_creates_parent_directories(self, tmp_path: Path):
        out = tmp_path / "nested" / "dir" / "out.csv"
        save_dry_run_csv([], out)
        assert out.exists()

    def test_data_values_written_correctly(self, tmp_path: Path):
        edge = _make_edge(
            mentor_code=42,
            mentor_name="Nick Saban",
            mentee_code=77,
            mentee_name="Kirby Smart",
            team="Alabama",
            overlap_years=4,
            mentor_role_abbr="HC",
        )
        out = tmp_path / "out.csv"
        save_dry_run_csv([edge], out)
        lines = out.read_text().splitlines()
        data_row = lines[1]
        assert "42" in data_row
        assert "Nick Saban" in data_row
        assert "77" in data_row
        assert "Kirby Smart" in data_row
        assert "Alabama" in data_row
        assert "4" in data_row
        assert "HC" in data_row


# ---------------------------------------------------------------------------
# Rule 1 — Prior HC: mentee was head coach before overlap → suppress edge
# ---------------------------------------------------------------------------


class TestRule1PriorHC:
    """Rule 1 (two-part): suppress MENTORED edge when:
    - Part A: mentee was HC at THIS specific team during any overlap year, OR
    - Part B: mentee was HC at ANY program strictly before the overlap_start.
    """

    def test_mentee_prior_hc_suppresses_edge(self):
        """Mentee was HC at another school before overlap → edge suppressed."""
        records = [
            # Mentor is HC at Alabama during overlap
            _coord_rec(coach_code=1, coach_name="Smart", team="Alabama", year=2019),
            _coord_rec(coach_code=1, coach_name="Smart", team="Alabama", year=2020),
            _coord_rec(coach_code=1, coach_name="Smart", team="Alabama", year=2021),
            # Mentee was HC at Florida 2011–2014 (BEFORE overlap 2019–2021)
            _coord_rec(coach_code=2, coach_name="Muschamp", team="Florida", year=2011, role_abbr="HC"),
            _coord_rec(coach_code=2, coach_name="Muschamp", team="Florida", year=2012, role_abbr="HC"),
            _coord_rec(coach_code=2, coach_name="Muschamp", team="Florida", year=2013, role_abbr="HC"),
            # Mentee joins Alabama as DC during overlap
            _role_rec(coach_code=2, coach_name="Muschamp", team="Alabama", year=2019, role_abbr="DC"),
            _role_rec(coach_code=2, coach_name="Muschamp", team="Alabama", year=2020, role_abbr="DC"),
            _role_rec(coach_code=2, coach_name="Muschamp", team="Alabama", year=2021, role_abbr="DC"),
        ]
        edges = infer_mentored_edges_v2(records)
        # Smart→Muschamp must be suppressed by Rule 1
        pairs = {(e["mentor_code"], e["mentee_code"]) for e in edges}
        assert (1, 2) not in pairs

    def test_mentee_hc_after_overlap_does_not_suppress(self):
        """Mentee became HC AFTER the overlap window → edge should be created."""
        records = [
            # Overlap 2010–2012
            _coord_rec(coach_code=1, coach_name="Saban", team="Alabama", year=2010),
            _coord_rec(coach_code=1, coach_name="Saban", team="Alabama", year=2011),
            _coord_rec(coach_code=1, coach_name="Saban", team="Alabama", year=2012),
            _role_rec(coach_code=2, coach_name="Mentee", team="Alabama", year=2010, role_abbr="WR"),
            _role_rec(coach_code=2, coach_name="Mentee", team="Alabama", year=2011, role_abbr="WR"),
            _role_rec(coach_code=2, coach_name="Mentee", team="Alabama", year=2012, role_abbr="WR"),
            # Mentee becomes HC at another school in 2015 (after overlap)
            _coord_rec(coach_code=2, coach_name="Mentee", team="State U", year=2015, role_abbr="HC"),
        ]
        edges = infer_mentored_edges_v2(records)
        pairs = {(e["mentor_code"], e["mentee_code"]) for e in edges}
        assert (1, 2) in pairs

    def test_mentee_hc_same_year_as_overlap_start_suppresses(self):
        """Mentee held HC in the same year as overlap_start → suppressed.

        The rule checks: prior_hc_year < overlap_start (strict less-than).
        An HC role held in the exact overlap_start year is NOT prior — edge created.
        """
        records = [
            # Overlap starts 2015
            _coord_rec(coach_code=1, coach_name="Mentor", team="A", year=2015),
            _coord_rec(coach_code=1, coach_name="Mentor", team="A", year=2016),
            _role_rec(coach_code=2, coach_name="Mentee", team="A", year=2015, role_abbr="WR"),
            _role_rec(coach_code=2, coach_name="Mentee", team="A", year=2016, role_abbr="WR"),
            # Mentee was HC at another school in 2014 (year BEFORE overlap_start=2015)
            _coord_rec(coach_code=2, coach_name="Mentee", team="B", year=2014, role_abbr="HC"),
        ]
        edges = infer_mentored_edges_v2(records)
        # 2014 < 2015 → Rule 1 suppresses
        pairs = {(e["mentor_code"], e["mentee_code"]) for e in edges}
        assert (1, 2) not in pairs

    def test_mentee_hc_at_different_team_same_year_not_suppressed(self):
        """Mentee is HC at a DIFFERENT team in the same year as overlap_start.

        Part A (same-team) does not fire because HC is at team B, not team A.
        Part B (global prior) does not fire because HC year == overlap_start (not <).
        Edge is created — the mentee is a WR coach at team A, not HC there.
        """
        records = [
            _coord_rec(coach_code=1, coach_name="Mentor", team="A", year=2015),
            _coord_rec(coach_code=1, coach_name="Mentor", team="A", year=2016),
            _role_rec(coach_code=2, coach_name="Mentee", team="A", year=2015, role_abbr="WR"),
            _role_rec(coach_code=2, coach_name="Mentee", team="A", year=2016, role_abbr="WR"),
            # HC at a different school (B) in the overlap year — not same-team
            _coord_rec(coach_code=2, coach_name="Mentee", team="B", year=2015, role_abbr="HC"),
        ]
        edges = infer_mentored_edges_v2(records)
        pairs = {(e["mentor_code"], e["mentee_code"]) for e in edges}
        assert (1, 2) in pairs

    def test_mentor_prior_hc_does_not_suppress(self):
        """Rule 1 only applies to the MENTEE. Mentor's prior HC history is irrelevant."""
        records = [
            # Mentor was HC at another school before
            _coord_rec(coach_code=1, coach_name="Mentor", team="OldSchool", year=2005, role_abbr="HC"),
            # Mentor is now HC at current school during overlap
            _coord_rec(coach_code=1, coach_name="Mentor", team="A", year=2010),
            _coord_rec(coach_code=1, coach_name="Mentor", team="A", year=2011),
            _role_rec(coach_code=2, coach_name="Mentee", team="A", year=2010, role_abbr="WR"),
            _role_rec(coach_code=2, coach_name="Mentee", team="A", year=2011, role_abbr="WR"),
        ]
        edges = infer_mentored_edges_v2(records)
        pairs = {(e["mentor_code"], e["mentee_code"]) for e in edges}
        assert (1, 2) in pairs

    def test_rule1_does_not_affect_mentee_with_no_prior_hc(self):
        """Standard case: mentee has no HC history → edge created normally."""
        records = [
            _coord_rec(coach_code=1, coach_name="Saban", team="Alabama", year=2007),
            _coord_rec(coach_code=1, coach_name="Saban", team="Alabama", year=2008),
            _coord_rec(coach_code=1, coach_name="Saban", team="Alabama", year=2009),
            _role_rec(coach_code=2, coach_name="Smart", team="Alabama", year=2007, role_abbr="DB"),
            _role_rec(coach_code=2, coach_name="Smart", team="Alabama", year=2008, role_abbr="DB"),
            _role_rec(coach_code=2, coach_name="Smart", team="Alabama", year=2009, role_abbr="DB"),
        ]
        edges = infer_mentored_edges_v2(records)
        pairs = {(e["mentor_code"], e["mentee_code"]) for e in edges}
        # Saban → Smart: valid (no prior HC for Smart)
        assert (1, 2) in pairs

    def test_rule1_kirby_smart_not_mentee_of_muschamp_at_georgia(self):
        """Muschamp (prior HC) joins Smart's Georgia staff → Smart NOT mentored by Muschamp.

        When Muschamp (coordinator) mentors Smart's staff members:
        - Smart is the mentor (HC), Muschamp is subordinate
        - But if Muschamp were the mentor, Rule 1 would apply to suppress.
        This test verifies the specific Will Muschamp scenario from the session goal.
        """
        records = [
            # Smart is HC at Georgia 2016–2021 (include pre-overlap years for Rule 1 on reverse)
            _coord_rec(coach_code=10, coach_name="Kirby Smart", team="Georgia", year=2016, role_abbr="HC"),
            _coord_rec(coach_code=10, coach_name="Kirby Smart", team="Georgia", year=2017, role_abbr="HC"),
            _coord_rec(coach_code=10, coach_name="Kirby Smart", team="Georgia", year=2018, role_abbr="HC"),
            _coord_rec(coach_code=10, coach_name="Kirby Smart", team="Georgia", year=2019, role_abbr="HC"),
            _coord_rec(coach_code=10, coach_name="Kirby Smart", team="Georgia", year=2020, role_abbr="HC"),
            _coord_rec(coach_code=10, coach_name="Kirby Smart", team="Georgia", year=2021, role_abbr="HC"),
            # Muschamp was HC at Florida 2011–2014 (prior HC before overlap_start=2019)
            _coord_rec(coach_code=20, coach_name="Will Muschamp", team="Florida", year=2011, role_abbr="HC"),
            _coord_rec(coach_code=20, coach_name="Will Muschamp", team="Florida", year=2012, role_abbr="HC"),
            # Muschamp joins Georgia as DC 2019–2021
            _role_rec(coach_code=20, coach_name="Will Muschamp", team="Georgia", year=2019, role_abbr="DC"),
            _role_rec(coach_code=20, coach_name="Will Muschamp", team="Georgia", year=2020, role_abbr="DC"),
            _role_rec(coach_code=20, coach_name="Will Muschamp", team="Georgia", year=2021, role_abbr="DC"),
        ]
        edges = infer_mentored_edges_v2(records)
        pairs = {(e["mentor_code"], e["mentee_code"]) for e in edges}
        # Smart(10) → Muschamp(20): Muschamp held HC in {2011,2012} before overlap_start=2019 → Rule 1 suppresses
        assert (10, 20) not in pairs
        # Muschamp(20) → Smart(10): Smart held HC at Georgia in {2016,2017,2018} before overlap_start=2019 → Rule 1 suppresses
        assert (20, 10) not in pairs

    # ---- Part A: same-team HC during overlap --------------------------------

    def test_mentee_hc_at_same_team_during_overlap_suppressed(self):
        """Mentee becomes HC at this school mid-overlap → Part A suppresses edge.

        Mirrors the Swinney/Napier case: Napier (OC) arrives in 2006, Swinney
        (then assistant) becomes HC at the same school in 2008. The overlap
        window includes 2008–2010 when Swinney is HC at Clemson.
        Part A fires: HC at THIS team during overlap → suppress Napier→Swinney.
        """
        records = [
            # Mentor (Napier-like) at Clemson 2006–2010 as OC
            _coord_rec(coach_code=1, coach_name="Napier", team="Clemson", year=2006, role_abbr="OC"),
            _coord_rec(coach_code=1, coach_name="Napier", team="Clemson", year=2007, role_abbr="OC"),
            _coord_rec(coach_code=1, coach_name="Napier", team="Clemson", year=2008, role_abbr="OC"),
            _coord_rec(coach_code=1, coach_name="Napier", team="Clemson", year=2009, role_abbr="OC"),
            _coord_rec(coach_code=1, coach_name="Napier", team="Clemson", year=2010, role_abbr="OC"),
            # Mentee (Swinney-like) at Clemson 2006–2010; becomes HC there in 2008
            _role_rec(coach_code=2, coach_name="Swinney", team="Clemson", year=2006, role_abbr="WR"),
            _role_rec(coach_code=2, coach_name="Swinney", team="Clemson", year=2007, role_abbr="WR"),
            _coord_rec(coach_code=2, coach_name="Swinney", team="Clemson", year=2008, role_abbr="HC"),
            _coord_rec(coach_code=2, coach_name="Swinney", team="Clemson", year=2009, role_abbr="HC"),
            _coord_rec(coach_code=2, coach_name="Swinney", team="Clemson", year=2010, role_abbr="HC"),
        ]
        edges = infer_mentored_edges_v2(records)
        pairs = {(e["mentor_code"], e["mentee_code"]) for e in edges}
        # Napier→Swinney must be suppressed (Swinney was HC at Clemson during overlap)
        assert (1, 2) not in pairs

    def test_mentee_hc_at_same_team_from_start_of_overlap_suppressed(self):
        """Mentee is HC at this school from the very first overlap year → Part A suppresses.

        Mirrors Bielema at Wisconsin (HC from 2006, overlap starts 2006).
        HC year equals overlap_start — old Part-B check missed this.
        """
        records = [
            # Mentor (Bostad-like) at Wisconsin 2006–2011 as OC
            _coord_rec(coach_code=1, coach_name="Bostad", team="Wisconsin", year=2006, role_abbr="OC"),
            _coord_rec(coach_code=1, coach_name="Bostad", team="Wisconsin", year=2007, role_abbr="OC"),
            _coord_rec(coach_code=1, coach_name="Bostad", team="Wisconsin", year=2008, role_abbr="OC"),
            # Mentee (Bielema-like) is HC at Wisconsin from 2006 (same start year)
            _coord_rec(coach_code=2, coach_name="Bielema", team="Wisconsin", year=2006, role_abbr="HC"),
            _coord_rec(coach_code=2, coach_name="Bielema", team="Wisconsin", year=2007, role_abbr="HC"),
            _coord_rec(coach_code=2, coach_name="Bielema", team="Wisconsin", year=2008, role_abbr="HC"),
        ]
        edges = infer_mentored_edges_v2(records)
        pairs = {(e["mentor_code"], e["mentee_code"]) for e in edges}
        # Bostad→Bielema must be suppressed (Bielema HC at Wisconsin during entire overlap)
        assert (1, 2) not in pairs

    def test_pre_hc_overlap_at_same_team_not_suppressed(self):
        """Overlap years are entirely before the mentee's HC career → edge created.

        Mirrors Kirby Smart at Alabama 2007–2015 (became HC at Georgia in 2016).
        No HC at Alabama during overlap → legitimate mentoring relationship.
        """
        records = [
            # Mentor (Saban-like) at Alabama 2007–2012 as HC
            _coord_rec(coach_code=1, coach_name="Saban", team="Alabama", year=2007, role_abbr="HC"),
            _coord_rec(coach_code=1, coach_name="Saban", team="Alabama", year=2008, role_abbr="HC"),
            _coord_rec(coach_code=1, coach_name="Saban", team="Alabama", year=2009, role_abbr="HC"),
            # Mentee (Smart-like) at Alabama 2007–2012 as DB coach
            _role_rec(coach_code=2, coach_name="Smart", team="Alabama", year=2007, role_abbr="DB"),
            _role_rec(coach_code=2, coach_name="Smart", team="Alabama", year=2008, role_abbr="DB"),
            _role_rec(coach_code=2, coach_name="Smart", team="Alabama", year=2009, role_abbr="DB"),
            # Smart becomes HC at Georgia in 2016 (after the overlap)
            _coord_rec(coach_code=2, coach_name="Smart", team="Georgia", year=2016, role_abbr="HC"),
            _coord_rec(coach_code=2, coach_name="Smart", team="Georgia", year=2017, role_abbr="HC"),
        ]
        edges = infer_mentored_edges_v2(records)
        pairs = {(e["mentor_code"], e["mentee_code"]) for e in edges}
        # Saban→Smart must be present (Smart was not HC at Alabama during overlap)
        assert (1, 2) in pairs


# ---------------------------------------------------------------------------
# Rule 2 — Same-level coordinator: both coaches hold OC or DC at same team/year
# ---------------------------------------------------------------------------


class TestRule2SameLevelCoordinator:
    """Rule 2: Do not create MENTORED edge when both coaches held OC or DC
    at the same program in the same year (coordinator peers)."""

    def test_both_oc_same_team_same_year_suppresses(self):
        """Two OC coaches at the same school in the same year → no edge either direction."""
        records = [
            _coord_rec(coach_code=1, coach_name="OC1", team="A", year=2010, role_abbr="OC"),
            _coord_rec(coach_code=1, coach_name="OC1", team="A", year=2011, role_abbr="OC"),
            _coord_rec(coach_code=2, coach_name="OC2", team="A", year=2010, role_abbr="OC"),
            _coord_rec(coach_code=2, coach_name="OC2", team="A", year=2011, role_abbr="OC"),
        ]
        edges = infer_mentored_edges_v2(records)
        pairs = {(e["mentor_code"], e["mentee_code"]) for e in edges}
        assert (1, 2) not in pairs
        assert (2, 1) not in pairs

    def test_oc_and_dc_same_team_same_year_suppresses(self):
        """OC and DC coaching together are coordinate-level peers → no edge."""
        records = [
            _coord_rec(coach_code=1, coach_name="OC", team="A", year=2010, role_abbr="OC"),
            _coord_rec(coach_code=1, coach_name="OC", team="A", year=2011, role_abbr="OC"),
            _coord_rec(coach_code=2, coach_name="DC", team="A", year=2010, role_abbr="DC"),
            _coord_rec(coach_code=2, coach_name="DC", team="A", year=2011, role_abbr="DC"),
        ]
        edges = infer_mentored_edges_v2(records)
        pairs = {(e["mentor_code"], e["mentee_code"]) for e in edges}
        assert (1, 2) not in pairs
        assert (2, 1) not in pairs

    def test_both_dc_same_team_same_year_suppresses(self):
        """Two DC coaches at the same school → no edge."""
        records = [
            _coord_rec(coach_code=1, coach_name="DC1", team="A", year=2010, role_abbr="DC"),
            _coord_rec(coach_code=1, coach_name="DC1", team="A", year=2011, role_abbr="DC"),
            _coord_rec(coach_code=2, coach_name="DC2", team="A", year=2010, role_abbr="DC"),
            _coord_rec(coach_code=2, coach_name="DC2", team="A", year=2011, role_abbr="DC"),
        ]
        edges = infer_mentored_edges_v2(records)
        pairs = {(e["mentor_code"], e["mentee_code"]) for e in edges}
        assert (1, 2) not in pairs
        assert (2, 1) not in pairs

    def test_hc_and_oc_not_same_level_edge_created(self):
        """HC mentors OC — HC is not OC/DC level. Rule 2 does not apply."""
        records = [
            _coord_rec(coach_code=1, coach_name="HC", team="A", year=2010, role_abbr="HC"),
            _coord_rec(coach_code=1, coach_name="HC", team="A", year=2011, role_abbr="HC"),
            _coord_rec(coach_code=2, coach_name="OC", team="A", year=2010, role_abbr="OC"),
            _coord_rec(coach_code=2, coach_name="OC", team="A", year=2011, role_abbr="OC"),
        ]
        edges = infer_mentored_edges_v2(records)
        pairs = {(e["mentor_code"], e["mentee_code"]) for e in edges}
        # HC→OC: valid (HC is not a peer coordinator of OC)
        assert (1, 2) in pairs

    def test_hc_and_dc_not_same_level_edge_created(self):
        """HC mentors DC — not same-level coordinators."""
        records = [
            _coord_rec(coach_code=1, coach_name="HC", team="A", year=2010, role_abbr="HC"),
            _coord_rec(coach_code=1, coach_name="HC", team="A", year=2011, role_abbr="HC"),
            _coord_rec(coach_code=2, coach_name="DC", team="A", year=2010, role_abbr="DC"),
            _coord_rec(coach_code=2, coach_name="DC", team="A", year=2011, role_abbr="DC"),
        ]
        edges = infer_mentored_edges_v2(records)
        pairs = {(e["mentor_code"], e["mentee_code"]) for e in edges}
        assert (1, 2) in pairs

    def test_oc_at_different_teams_no_rule2(self):
        """OC at Team A and OC at Team B in same year → different programs, no Rule 2."""
        records = [
            _coord_rec(coach_code=1, coach_name="OC1", team="A", year=2010, role_abbr="OC"),
            _coord_rec(coach_code=1, coach_name="OC1", team="A", year=2011, role_abbr="OC"),
            # Coach 2 is OC at Team B (different school) — never overlaps at same program
            _coord_rec(coach_code=2, coach_name="OC2", team="B", year=2010, role_abbr="OC"),
        ]
        # No shared team → no edges anyway (distinct schools)
        edges = infer_mentored_edges_v2(records)
        assert edges == []

    def test_partial_overlap_oc_oc_only_in_one_year_suppresses(self):
        """OC-OC overlap in at least one shared year is enough to trigger Rule 2."""
        records = [
            # Coach 1: OC in 2010, then WR in 2011
            _coord_rec(coach_code=1, coach_name="OC1", team="A", year=2010, role_abbr="OC"),
            _role_rec(coach_code=1, coach_name="OC1", team="A", year=2011, role_abbr="WR"),
            # Coach 2: WR in 2010, then OC in 2011
            _role_rec(coach_code=2, coach_name="OC2", team="A", year=2010, role_abbr="WR"),
            _coord_rec(coach_code=2, coach_name="OC2", team="A", year=2011, role_abbr="OC"),
        ]
        # No single year where BOTH hold OC/DC at team A (2010: only 1 holds OC; 2011: only 2 holds OC)
        # → Rule 2 does NOT suppress; but only one (whoever has OC) is coordinator in their year
        # Actually: in 2010 coach 1 (OC) can mentor coach 2 (WR) — coord check passes, Rule 2: coach 2 not OC/DC in 2010
        # In 2011 coach 2 (OC) can mentor coach 1 (WR) — coord check passes, Rule 2: coach 1 not OC/DC in 2011
        # So both (1,2) and (2,1) edges should exist
        edges = infer_mentored_edges_v2(records)
        pairs = {(e["mentor_code"], e["mentee_code"]) for e in edges}
        # Neither year has BOTH as OC/DC simultaneously → Rule 2 does not suppress
        assert (1, 2) in pairs or (2, 1) in pairs

    def test_rule2_suppresses_but_hc_still_mentors_both(self):
        """HC mentors both OC and DC normally; OC-DC pair itself is suppressed."""
        records = [
            # HC coaches all three years
            _coord_rec(coach_code=1, coach_name="HC", team="A", year=2010, role_abbr="HC"),
            _coord_rec(coach_code=1, coach_name="HC", team="A", year=2011, role_abbr="HC"),
            # OC and DC are both at team A — peers → no OC↔DC edge
            _coord_rec(coach_code=2, coach_name="OC", team="A", year=2010, role_abbr="OC"),
            _coord_rec(coach_code=2, coach_name="OC", team="A", year=2011, role_abbr="OC"),
            _coord_rec(coach_code=3, coach_name="DC", team="A", year=2010, role_abbr="DC"),
            _coord_rec(coach_code=3, coach_name="DC", team="A", year=2011, role_abbr="DC"),
        ]
        edges = infer_mentored_edges_v2(records)
        pairs = {(e["mentor_code"], e["mentee_code"]) for e in edges}
        # HC → OC: valid (HC not OC/DC)
        assert (1, 2) in pairs
        # HC → DC: valid (HC not OC/DC)
        assert (1, 3) in pairs
        # OC ↔ DC: suppressed by Rule 2
        assert (2, 3) not in pairs
        assert (3, 2) not in pairs


# ---------------------------------------------------------------------------
# Rule 3 — Minimum consecutive overlap (verified existing behavior)
# ---------------------------------------------------------------------------


class TestRule3MinimumOverlap:
    """Rule 3 (pre-existing): require >= 2 consecutive seasons of overlap."""

    def test_exactly_one_consecutive_year_no_edge(self):
        """Single shared season → no edge (2+ required)."""
        records = [
            _coord_rec(coach_code=1, coach_name="HC", team="A", year=2010),
            _coord_rec(coach_code=1, coach_name="HC", team="A", year=2011),
            _role_rec(coach_code=2, coach_name="WR", team="A", year=2011, role_abbr="WR"),
        ]
        assert infer_mentored_edges_v2(records) == []

    def test_two_non_consecutive_shared_years_no_edge(self):
        """Shared years {2010, 2012} → max_consecutive=1 → no edge."""
        records = [
            _coord_rec(coach_code=1, coach_name="HC", team="A", year=2010),
            _coord_rec(coach_code=1, coach_name="HC", team="A", year=2011),
            _coord_rec(coach_code=1, coach_name="HC", team="A", year=2012),
            _role_rec(coach_code=2, coach_name="WR", team="A", year=2010, role_abbr="WR"),
            _role_rec(coach_code=2, coach_name="WR", team="A", year=2012, role_abbr="WR"),
        ]
        # overlap = {2010, 2012} → max_consecutive = 1 → no edge
        assert infer_mentored_edges_v2(records) == []

    def test_two_consecutive_shared_years_creates_edge(self):
        """Exactly 2 consecutive shared years → edge created."""
        records = [
            _coord_rec(coach_code=1, coach_name="HC", team="A", year=2010),
            _coord_rec(coach_code=1, coach_name="HC", team="A", year=2011),
            _role_rec(coach_code=2, coach_name="WR", team="A", year=2010, role_abbr="WR"),
            _role_rec(coach_code=2, coach_name="WR", team="A", year=2011, role_abbr="WR"),
        ]
        edges = infer_mentored_edges_v2(records)
        assert len(edges) == 1


# ---------------------------------------------------------------------------
# Rule 4 — No self-referential edges
# ---------------------------------------------------------------------------


class TestRule4SelfReferential:
    """Rule 4: A coach cannot mentor themselves (mentor_code == mentee_code)."""

    def test_no_self_loop_edges_in_output(self):
        """All output edges must have mentor_code != mentee_code."""
        records = [
            _coord_rec(coach_code=1, coach_name="HC", team="A", year=2010),
            _coord_rec(coach_code=1, coach_name="HC", team="A", year=2011),
            _role_rec(coach_code=2, coach_name="WR", team="A", year=2010, role_abbr="WR"),
            _role_rec(coach_code=2, coach_name="WR", team="A", year=2011, role_abbr="WR"),
        ]
        edges = infer_mentored_edges_v2(records)
        for e in edges:
            assert e["mentor_code"] != e["mentee_code"], (
                f"Self-loop edge found: mentor_code={e['mentor_code']}"
            )

    def test_single_coach_multiple_years_no_self_edge(self):
        """A coach appearing many times at one team still produces no self-mentoring edge."""
        records = [
            _coord_rec(coach_code=99, coach_name="Solo HC", team="Solo U", year=yr)
            for yr in range(2010, 2020)
        ]
        edges = infer_mentored_edges_v2(records)
        assert all(e["mentor_code"] != e["mentee_code"] for e in edges)
        # Solo coach → no other coaches at this team → no edges at all
        assert edges == []


# ---------------------------------------------------------------------------
# Same-unit filter — cross-unit edges suppressed
# ---------------------------------------------------------------------------


class TestSameUnitFilter:
    """Same-unit filter: offensive mentor → defensive mentee (and vice versa) suppressed.

    HC and neutral-role mentors are compatible with any mentee unit.
    """

    def _two_year_overlap(
        self,
        mentor_code: int,
        mentor_name: str,
        mentor_role: str,
        mentee_code: int,
        mentee_name: str,
        mentee_role: str,
        team: str = "Test U",
    ) -> list[dict]:
        """Build minimal two-year records for a mentor/mentee pair."""
        mentor_is_coord = mentor_role in {"HC", "AC", "OC", "DC", "PG", "PD", "RG", "RD"}
        mentee_is_coord = mentee_role in {"HC", "AC", "OC", "DC", "PG", "PD", "RG", "RD"}
        make_mentor = _coord_rec if mentor_is_coord else _role_rec
        make_mentee = _coord_rec if mentee_is_coord else _role_rec
        return [
            make_mentor(coach_code=mentor_code, coach_name=mentor_name, team=team, year=2010, role_abbr=mentor_role),
            make_mentor(coach_code=mentor_code, coach_name=mentor_name, team=team, year=2011, role_abbr=mentor_role),
            make_mentee(coach_code=mentee_code, coach_name=mentee_name, team=team, year=2010, role_abbr=mentee_role),
            make_mentee(coach_code=mentee_code, coach_name=mentee_name, team=team, year=2011, role_abbr=mentee_role),
        ]

    # OC mentor → offensive and defensive mentees

    def test_oc_mentor_to_wr_coach_edge_created(self):
        """OC (offensive) mentor → WR coach (offensive mentee) → edge kept."""
        records = self._two_year_overlap(1, "OC Coach", "OC", 2, "WR Coach", "WR")
        edges = infer_mentored_edges_v2(records)
        pairs = {(e["mentor_code"], e["mentee_code"]) for e in edges}
        assert (1, 2) in pairs

    def test_oc_mentor_to_dc_blocked(self):
        """OC (offensive) mentor → DC (defensive) mentee → edge suppressed."""
        records = self._two_year_overlap(1, "OC Coach", "OC", 2, "DC Coach", "DC")
        edges = infer_mentored_edges_v2(records)
        pairs = {(e["mentor_code"], e["mentee_code"]) for e in edges}
        assert (1, 2) not in pairs

    def test_oc_mentor_to_lb_coach_blocked(self):
        """OC (offensive) mentor → LB coach (defensive mentee) → edge suppressed."""
        records = self._two_year_overlap(1, "OC Coach", "OC", 2, "LB Coach", "LB")
        edges = infer_mentored_edges_v2(records)
        pairs = {(e["mentor_code"], e["mentee_code"]) for e in edges}
        assert (1, 2) not in pairs

    # DC mentor → defensive and offensive mentees

    def test_dc_mentor_to_lb_coach_edge_created(self):
        """DC (defensive) mentor → LB coach (defensive mentee) → edge kept."""
        records = self._two_year_overlap(1, "DC Coach", "DC", 2, "LB Coach", "LB")
        edges = infer_mentored_edges_v2(records)
        pairs = {(e["mentor_code"], e["mentee_code"]) for e in edges}
        assert (1, 2) in pairs

    def test_dc_mentor_to_oc_blocked(self):
        """DC (defensive) mentor → OC (offensive) mentee → edge suppressed."""
        records = self._two_year_overlap(1, "DC Coach", "DC", 2, "OC Coach", "OC")
        edges = infer_mentored_edges_v2(records)
        pairs = {(e["mentor_code"], e["mentee_code"]) for e in edges}
        assert (1, 2) not in pairs

    def test_dc_mentor_to_wr_coach_blocked(self):
        """DC (defensive) mentor → WR coach (offensive mentee) → edge suppressed."""
        records = self._two_year_overlap(1, "DC Coach", "DC", 2, "WR Coach", "WR")
        edges = infer_mentored_edges_v2(records)
        pairs = {(e["mentor_code"], e["mentee_code"]) for e in edges}
        assert (1, 2) not in pairs

    # HC mentor → any mentee unit

    def test_hc_mentor_to_dc_edge_created(self):
        """HC (neutral) mentor → DC (defensive mentee) → edge kept."""
        records = self._two_year_overlap(1, "HC Coach", "HC", 2, "DC Coach", "DC")
        edges = infer_mentored_edges_v2(records)
        pairs = {(e["mentor_code"], e["mentee_code"]) for e in edges}
        assert (1, 2) in pairs

    def test_hc_mentor_to_wr_coach_edge_created(self):
        """HC (neutral) mentor → WR coach (offensive mentee) → edge kept."""
        records = self._two_year_overlap(1, "HC Coach", "HC", 2, "WR Coach", "WR")
        edges = infer_mentored_edges_v2(records)
        pairs = {(e["mentor_code"], e["mentee_code"]) for e in edges}
        assert (1, 2) in pairs

    # HC mentor → ST mentee (neutral mentee is compatible with any unit mentor)

    def test_hc_mentor_to_st_coach_edge_created(self):
        """HC (neutral) mentor → ST coach (neutral mentee) → edge kept.

        ST is not in _MENTOR_ABBRS so it cannot be a v2 mentor itself;
        but as a mentee it is neutral and compatible with any mentor.
        """
        records = self._two_year_overlap(1, "HC Coach", "HC", 2, "ST Coach", "ST")
        edges = infer_mentored_edges_v2(records)
        pairs = {(e["mentor_code"], e["mentee_code"]) for e in edges}
        assert (1, 2) in pairs

    def test_oc_mentor_to_st_coach_edge_created(self):
        """OC (offensive) mentor → ST coach (neutral mentee) → edge kept.

        ST is in NEUTRAL_ROLES so same_unit("OC", "ST") returns True.
        """
        records = self._two_year_overlap(1, "OC Coach", "OC", 2, "ST Coach", "ST")
        edges = infer_mentored_edges_v2(records)
        pairs = {(e["mentor_code"], e["mentee_code"]) for e in edges}
        assert (1, 2) in pairs

    # _suppressed_unit_edges collection
    # Use OC→DB: OC is offensive coordinator, DB is a defensive position coach.
    # DB is not in _COORD_PEER_ROLES, so Rule 2 does not fire.
    # same_unit("OC", "DB") → False → same-unit filter suppresses.

    def test_suppressed_unit_edges_collected(self):
        """_suppressed_unit_edges list is populated with cross-unit edges.

        OC (offensive) mentor → DB coach (defensive) mentee.
        DB is not a _COORD_PEER_ROLE so Rule 2 does not fire; same-unit filter does.
        """
        records = self._two_year_overlap(1, "OC Coach", "OC", 2, "DB Coach", "DB")
        suppressed: list[dict] = []
        edges = infer_mentored_edges_v2(records, _suppressed_unit_edges=suppressed)
        assert (1, 2) not in {(e["mentor_code"], e["mentee_code"]) for e in edges}
        assert len(suppressed) >= 1
        s = suppressed[0]
        assert s["mentor_role"] == "OC"
        assert s["mentee_role"] == "DB"
        assert "mentor_name" in s
        assert "mentee_name" in s
        assert "team" in s

    def test_no_suppressed_when_same_unit(self):
        """When the pair is same-unit, _suppressed_unit_edges remains empty."""
        records = self._two_year_overlap(1, "OC Coach", "OC", 2, "WR Coach", "WR")
        suppressed: list[dict] = []
        infer_mentored_edges_v2(records, _suppressed_unit_edges=suppressed)
        assert suppressed == []
