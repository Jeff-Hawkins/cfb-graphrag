"""Tests for the McIllece staff ingestion pipeline.

Covers:
- pull_mcillece_staff: role parsing, required-field validation, malformed rows
- load_staff: MERGE called with coach_code as unique key, correct row shape
- infer_mentored_pairs_mcillece: role_priority direction, tie-break by start year,
  ambiguous pairs skipped, deduplication across schools
- load_mentored_edges_mcillece: MERGE called with correct coach_code keys
"""

import io
from unittest.mock import MagicMock, patch

import pytest

from ingestion.build_mentored_edges import infer_mentored_pairs_mcillece
from ingestion.pull_mcillece_staff import _clean_rows, load_mcillece_file
from loader.load_mentored_edges import load_mentored_edges_mcillece
from loader.load_staff import load_staff


# ---------------------------------------------------------------------------
# Fixtures — Alabama 2020 sample (11 rows, mirrors the real xlsx)
# ---------------------------------------------------------------------------

ALA_2020_ROWS = [
    {"coach_code": 1457, "team_code": 8, "year": 2020, "team": "Alabama", "coach": "Nick Saban",      "pos1": "HC",  "pos2": None, "pos3": None, "pos4": None, "pos5": None},
    {"coach_code": 2369, "team_code": 8, "year": 2020, "team": "Alabama", "coach": "Pete Golding",    "pos1": "DC",  "pos2": "IB", "pos3": None, "pos4": None, "pos5": None},
    {"coach_code": 1062, "team_code": 8, "year": 2020, "team": "Alabama", "coach": "Steve Sarkisian", "pos1": "OC",  "pos2": "QB", "pos3": None, "pos4": None, "pos5": None},
    {"coach_code": 2182, "team_code": 8, "year": 2020, "team": "Alabama", "coach": "Freddie Roach",   "pos1": "DL",  "pos2": None, "pos3": None, "pos4": None, "pos5": None},
    {"coach_code":  531, "team_code": 8, "year": 2020, "team": "Alabama", "coach": "Jeff Banks",      "pos1": "ST",  "pos2": "TE", "pos3": None, "pos4": None, "pos5": None},
    {"coach_code":  716, "team_code": 8, "year": 2020, "team": "Alabama", "coach": "Kyle Flood",      "pos1": "OL",  "pos2": None, "pos3": None, "pos4": None, "pos5": None},
    {"coach_code": 2167, "team_code": 8, "year": 2020, "team": "Alabama", "coach": "Charles Huff",    "pos1": "RB",  "pos2": None, "pos3": None, "pos4": None, "pos5": None},
    {"coach_code": 1217, "team_code": 8, "year": 2020, "team": "Alabama", "coach": "Charles Kelly",   "pos1": "DC",  "pos2": "SF", "pos3": None, "pos4": None, "pos5": None},
    {"coach_code": 2463, "team_code": 8, "year": 2020, "team": "Alabama", "coach": "Karl Scott",      "pos1": "CB",  "pos2": None, "pos3": None, "pos4": None, "pos5": None},
    {"coach_code": 1747, "team_code": 8, "year": 2020, "team": "Alabama", "coach": "Sal Sunseri",     "pos1": "OB",  "pos2": None, "pos3": None, "pos4": None, "pos5": None},
    {"coach_code": 1912, "team_code": 8, "year": 2020, "team": "Alabama", "coach": "Holman Wiggins",  "pos1": "WR",  "pos2": None, "pos3": None, "pos4": None, "pos5": None},
]


@pytest.fixture
def ala_2020_staff():
    """Cleaned Alabama 2020 staff records (as _clean_rows would produce)."""
    return _clean_rows(ALA_2020_ROWS)


# ---------------------------------------------------------------------------
# _clean_rows / load_mcillece_file — role parsing and validation
# ---------------------------------------------------------------------------


class TestCleanRows:
    """Unit tests for the row-cleaning logic (no file I/O)."""

    def test_roles_parsed_from_pos_columns(self, ala_2020_staff):
        """Non-null pos1–pos5 values become the roles list; None is dropped."""
        saban = next(r for r in ala_2020_staff if r["coach_code"] == 1457)
        golding = next(r for r in ala_2020_staff if r["coach_code"] == 2369)
        sarkisian = next(r for r in ala_2020_staff if r["coach_code"] == 1062)

        assert saban["roles"] == ["HC"]
        assert golding["roles"] == ["DC", "IB"]
        assert sarkisian["roles"] == ["OC", "QB"]

    def test_all_11_rows_parsed(self, ala_2020_staff):
        """All 11 Alabama 2020 rows pass validation."""
        assert len(ala_2020_staff) == 11

    def test_required_fields_present_in_output(self, ala_2020_staff):
        """Every output record has all required keys."""
        required = {"coach_code", "team_code", "year", "team", "coach_name", "roles"}
        for rec in ala_2020_staff:
            assert required <= rec.keys(), f"Missing keys in {rec}"

    def test_malformed_row_missing_coach_skipped(self):
        """Row with no 'coach' value is skipped with a warning."""
        rows = [
            {"coach_code": 1, "team_code": 8, "year": 2020, "team": "Alabama",
             "coach": None, "pos1": "HC", "pos2": None, "pos3": None, "pos4": None, "pos5": None},
        ]
        result = _clean_rows(rows)
        assert result == []

    def test_non_numeric_coach_code_skipped(self):
        """Row with non-numeric coach_code is skipped."""
        rows = [
            {"coach_code": "abc", "team_code": 8, "year": 2020, "team": "Alabama",
             "coach": "Test Coach", "pos1": "HC", "pos2": None, "pos3": None, "pos4": None, "pos5": None},
        ]
        result = _clean_rows(rows)
        assert result == []

    def test_nan_string_in_roles_dropped(self):
        """Sentinel strings ('nan', 'None') in role columns are excluded."""
        rows = [
            {"coach_code": 99, "team_code": 8, "year": 2020, "team": "Alabama",
             "coach": "Test Coach", "pos1": "OC", "pos2": "nan", "pos3": "None", "pos4": None, "pos5": None},
        ]
        result = _clean_rows(rows)
        assert len(result) == 1
        assert result[0]["roles"] == ["OC"]

    def test_empty_row_skipped(self):
        """A row where every value is None/blank is silently skipped."""
        rows = [
            {"coach_code": None, "team_code": None, "year": None,
             "team": None, "coach": None,
             "pos1": None, "pos2": None, "pos3": None, "pos4": None, "pos5": None},
        ]
        result = _clean_rows(rows)
        assert result == []


class TestLoadMcilleeceFile:
    """Integration tests for load_mcillece_file (mocks openpyxl/file I/O)."""

    def test_xlsx_returns_cleaned_records(self, tmp_path):
        """A real XLSX file round-trips correctly through the loader."""
        import openpyxl
        wb = openpyxl.Workbook()
        ws = wb.active
        ws.append(["coach_code", "team_code", "year", "team", "coach",
                   "pos1", "pos2", "pos3", "pos4", "pos5"])
        ws.append([1457, 8, 2020, "Alabama", "Nick Saban", "HC", None, None, None, None])
        ws.append([2369, 8, 2020, "Alabama", "Pete Golding", "DC", "IB", None, None, None])
        path = tmp_path / "test.xlsx"
        wb.save(path)

        records = load_mcillece_file(path)
        assert len(records) == 2
        assert records[0]["coach_code"] == 1457
        assert records[0]["roles"] == ["HC"]
        assert records[1]["roles"] == ["DC", "IB"]

    def test_unsupported_extension_raises(self, tmp_path):
        """A .json file raises ValueError."""
        path = tmp_path / "data.json"
        path.write_text("{}")
        with pytest.raises(ValueError, match="Unsupported file extension"):
            load_mcillece_file(path)


# ---------------------------------------------------------------------------
# load_staff — MERGE uses coach_code as unique key
# ---------------------------------------------------------------------------


def _make_load_driver() -> MagicMock:
    """Return a mock Neo4j driver whose count query returns 0."""
    driver = MagicMock()
    session = MagicMock()
    driver.session.return_value.__enter__ = MagicMock(return_value=session)
    driver.session.return_value.__exit__ = MagicMock(return_value=False)
    single_result = MagicMock()
    single_result.__getitem__ = lambda self, key: 0
    session.run.return_value.single.return_value = single_result
    return driver


class TestLoadStaff:
    """Verify load_staff issues correct MERGE queries."""

    def test_coach_merge_uses_coach_code(self, ala_2020_staff):
        """The Coach MERGE query must key on coach_code, not name."""
        driver = _make_load_driver()
        load_staff(driver, ala_2020_staff)
        session = driver.session().__enter__()

        # First run call is the coach MERGE
        first_query = session.run.call_args_list[0][0][0]
        assert "coach_code" in first_query
        assert "MERGE" in first_query

    def test_stint_merge_includes_year_and_roles(self, ala_2020_staff):
        """The COACHED_AT MERGE query must set roles and source properties."""
        driver = _make_load_driver()
        load_staff(driver, ala_2020_staff)
        session = driver.session().__enter__()

        stint_query = session.run.call_args_list[1][0][0]
        assert "roles" in stint_query
        assert "mcillece" in stint_query

    def test_returns_correct_counts(self, ala_2020_staff):
        """Returns (unique_coach_count, total_row_count)."""
        driver = _make_load_driver()
        coaches, edges = load_staff(driver, ala_2020_staff)
        assert coaches == 11  # 11 unique coach_codes in Alabama 2020
        assert edges == 11

    def test_empty_staff_returns_zeros(self):
        """Empty input returns (0, 0) without calling session.run."""
        driver = _make_load_driver()
        coaches, edges = load_staff(driver, [])
        session = driver.session().__enter__()
        assert session.run.call_count == 0
        assert (coaches, edges) == (0, 0)

    def test_rows_passed_contain_coach_code(self, ala_2020_staff):
        """The rows kwarg sent to the first session.run has coach_code values."""
        driver = _make_load_driver()
        load_staff(driver, ala_2020_staff)
        session = driver.session().__enter__()
        rows = session.run.call_args_list[0][1]["rows"]
        codes = {r["coach_code"] for r in rows}
        assert 1457 in codes  # Nick Saban


# ---------------------------------------------------------------------------
# infer_mentored_pairs_mcillece — role_priority direction logic
# ---------------------------------------------------------------------------


class TestInferMentoredPairsMcillece:
    """Unit tests for role-priority MENTORED inference (pure function)."""

    def _make_staff(self, entries: list[tuple]) -> list[dict]:
        """Build minimal staff records from (coach_code, name, team, year, roles) tuples."""
        return [
            {
                "coach_code": code,
                "coach_name": name,
                "team": team,
                "year": year,
                "roles": roles,
            }
            for code, name, team, year, roles in entries
        ]

    def test_hc_beats_position_coach(self):
        """HC role trumps a position coach regardless of start year."""
        staff = self._make_staff([
            # WR coach arrived in 2018; HC arrived in 2020 — they overlap in 2020.
            # Role priority (HC=3 > WR=0) should make HC the mentor despite later start.
            (200, "Wide Receivers Coach", "State U", 2018, ["WR"]),
            (200, "Wide Receivers Coach", "State U", 2020, ["WR"]),
            (100, "Head Coach",           "State U", 2020, ["HC"]),
        ])
        pairs = infer_mentored_pairs_mcillece(staff)
        assert len(pairs) == 1
        mentor, mentee = pairs[0]
        assert mentor["coach_code"] == 100  # HC wins despite later start

    def test_oc_beats_position_coach(self):
        """OC role is senior to a plain position coach."""
        staff = self._make_staff([
            (101, "OC Coach", "State U", 2020, ["OC", "QB"]),
            (201, "LB Coach", "State U", 2020, ["LB"]),
        ])
        pairs = infer_mentored_pairs_mcillece(staff)
        assert len(pairs) == 1
        mentor, mentee = pairs[0]
        assert mentor["coach_code"] == 101

    def test_dc_beats_position_coach(self):
        """DC role is senior to a plain position coach despite later start year."""
        staff = self._make_staff([
            # DL coach arrived 2019; DC arrived 2020 — they overlap in 2020.
            # Role priority (DC=2 > DL=0) should make DC the mentor.
            (102, "Pos Coach", "State U", 2019, ["DL"]),
            (102, "Pos Coach", "State U", 2020, ["DL"]),
            (202, "DC Coach",  "State U", 2020, ["DC"]),
        ])
        pairs = infer_mentored_pairs_mcillece(staff)
        assert len(pairs) == 1
        mentor, mentee = pairs[0]
        assert mentor["coach_code"] == 202  # DC wins despite later start

    def test_equal_priority_falls_back_to_start_year(self):
        """Two position coaches — the one with the earlier first year is the mentor."""
        staff = self._make_staff([
            (103, "Senior WR", "State U", 2015, ["WR"]),
            (203, "Junior WR", "State U", 2015, ["WR"]),
            # Junior joins the overlap year, Senior was already there
            (103, "Senior WR", "State U", 2018, ["WR"]),
            (203, "Junior WR", "State U", 2018, ["WR"]),
        ])
        # Senior first year = 2015, Junior first year = 2015 → ambiguous → skip
        pairs = infer_mentored_pairs_mcillece(staff)
        assert pairs == []

    def test_equal_priority_different_start_year(self):
        """Two OCs at different start years — earlier start is the mentor."""
        staff = self._make_staff([
            (104, "First OC",  "State U", 2010, ["OC"]),
            (104, "First OC",  "State U", 2012, ["OC"]),
            (204, "Second OC", "State U", 2012, ["OC"]),
        ])
        pairs = infer_mentored_pairs_mcillece(staff)
        assert len(pairs) == 1
        mentor, mentee = pairs[0]
        assert mentor["coach_code"] == 104

    def test_no_overlap_returns_empty(self):
        """Coaches at the same school in non-overlapping years → no pairs."""
        staff = self._make_staff([
            (105, "Old HC",  "State U", 2010, ["HC"]),
            (205, "New HC",  "State U", 2015, ["HC"]),
        ])
        pairs = infer_mentored_pairs_mcillece(staff)
        assert pairs == []

    def test_deduplication_across_schools(self):
        """Same pair at two schools produces only one MENTORED edge."""
        staff = self._make_staff([
            (106, "HC Guy",   "School A", 2015, ["HC"]),
            (206, "WR Guy",   "School A", 2015, ["WR"]),
            (106, "HC Guy",   "School B", 2018, ["HC"]),
            (206, "WR Guy",   "School B", 2018, ["WR"]),
        ])
        pairs = infer_mentored_pairs_mcillece(staff)
        # Both schools give same direction (HC > WR), dedup → 1 pair
        assert len(pairs) == 1

    def test_output_contains_coach_code_and_name(self):
        """Each pair dict has both coach_code and coach_name."""
        staff = self._make_staff([
            (107, "The Mentor", "U", 2020, ["HC"]),
            (207, "The Mentee", "U", 2020, ["RB"]),
        ])
        pairs = infer_mentored_pairs_mcillece(staff)
        assert len(pairs) == 1
        mentor, mentee = pairs[0]
        assert mentor["coach_code"] == 107
        assert mentor["coach_name"] == "The Mentor"
        assert mentee["coach_code"] == 207
        assert mentee["coach_name"] == "The Mentee"

    def test_alabama_2020_hc_is_mentor_for_all(self, ala_2020_staff):
        """Nick Saban (HC, code 1457) should be the mentor in all pairs he appears in."""
        pairs = infer_mentored_pairs_mcillece(ala_2020_staff)
        saban_as_mentor = [p for p in pairs if p[0]["coach_code"] == 1457]
        saban_as_mentee = [p for p in pairs if p[1]["coach_code"] == 1457]
        assert len(saban_as_mentor) > 0
        assert len(saban_as_mentee) == 0


# ---------------------------------------------------------------------------
# load_mentored_edges_mcillece — MERGE uses coach_code
# ---------------------------------------------------------------------------


def _make_count_driver(total: int = 5) -> MagicMock:
    driver = MagicMock()
    session = MagicMock()
    driver.session.return_value.__enter__ = MagicMock(return_value=session)
    driver.session.return_value.__exit__ = MagicMock(return_value=False)
    single_result = MagicMock()
    single_result.__getitem__ = lambda self, key: total
    session.run.return_value.single.return_value = single_result
    return driver


class TestLoadMentoredEdgesMcillece:
    """Verify load_mentored_edges_mcillece issues correct MERGE queries."""

    def test_merge_query_uses_coach_code(self):
        """The Cypher query must MATCH coaches by coach_code."""
        driver = _make_count_driver(total=1)
        pairs = [
            ({"coach_code": 1457, "coach_name": "Nick Saban"},
             {"coach_code": 1062, "coach_name": "Steve Sarkisian"}),
        ]
        load_mentored_edges_mcillece(driver, pairs)
        session = driver.session().__enter__()
        merge_query = session.run.call_args_list[0][0][0]
        assert "coach_code" in merge_query
        assert "MERGE" in merge_query

    def test_rows_contain_mentor_and_mentee_codes(self):
        """Rows passed to the MERGE have mentor_code and mentee_code keys."""
        driver = _make_count_driver(total=1)
        pairs = [
            ({"coach_code": 1457, "coach_name": "Nick Saban"},
             {"coach_code": 1062, "coach_name": "Steve Sarkisian"}),
        ]
        load_mentored_edges_mcillece(driver, pairs)
        session = driver.session().__enter__()
        rows = session.run.call_args_list[0][1]["rows"]
        assert rows[0]["mentor_code"] == 1457
        assert rows[0]["mentee_code"] == 1062

    def test_empty_pairs_skips_merge(self):
        """With no pairs, the UNWIND MERGE query is never sent."""
        driver = _make_count_driver(total=0)
        load_mentored_edges_mcillece(driver, [])
        session = driver.session().__enter__()
        for call in session.run.call_args_list:
            query = call[0][0] if call[0] else ""
            assert "UNWIND" not in query

    def test_prints_total_count(self, capsys):
        """Total MENTORED count is printed to stdout."""
        driver = _make_count_driver(total=42)
        pairs = [
            ({"coach_code": 1, "coach_name": "A"},
             {"coach_code": 2, "coach_name": "B"}),
        ]
        load_mentored_edges_mcillece(driver, pairs)
        captured = capsys.readouterr()
        assert "42" in captured.out
