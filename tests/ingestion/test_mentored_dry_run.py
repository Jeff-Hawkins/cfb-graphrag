"""Tests for the v2 MENTORED edge dry-run helpers.

Covers:
- _max_consecutive: various year-set shapes
- infer_mentored_edges_v2: coordinator filter, consecutive-year requirement,
  per-team dedup, multiple mentors, edge metadata
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
        """HC and OC both mentor a WR coach → 2 edges to WR plus 2 between each other."""
        records = [
            _coord_rec(coach_code=10, coach_name="HC", team="A", year=2010),
            _coord_rec(coach_code=10, coach_name="HC", team="A", year=2011),
            _coord_rec(coach_code=20, coach_name="OC", team="A", year=2010, role_abbr="OC"),
            _coord_rec(coach_code=20, coach_name="OC", team="A", year=2011, role_abbr="OC"),
            _role_rec(coach_code=30, coach_name="WR", team="A", year=2010, role_abbr="WR"),
            _role_rec(coach_code=30, coach_name="WR", team="A", year=2011, role_abbr="WR"),
        ]
        edges = infer_mentored_edges_v2(records)
        # HC→WR, OC→WR, HC→OC, OC→HC  (both coords qualify as mentors)
        assert len(edges) == 4
        mentor_mentee_pairs = {(e["mentor_code"], e["mentee_code"]) for e in edges}
        assert (10, 30) in mentor_mentee_pairs  # HC → WR
        assert (20, 30) in mentor_mentee_pairs  # OC → WR

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
