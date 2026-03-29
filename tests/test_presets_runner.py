"""Tests for presets/runner.py — F2 preset runner."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

from presets.runner import (
    PresetResult,
    _build_tree_rows,
    _resolve_coach_code,
    _run_table_preset,
    _run_tree_preset,
    load_presets,
    run_preset,
)


# ---------------------------------------------------------------------------
# load_presets
# ---------------------------------------------------------------------------


def test_load_presets_returns_list():
    presets = load_presets()
    assert isinstance(presets, list)
    assert len(presets) == 5


def test_load_presets_required_fields():
    for p in load_presets():
        assert "id" in p, f"preset missing 'id': {p}"
        assert "name" in p, f"preset missing 'name': {p}"
        assert "result_type" in p, f"preset missing 'result_type': {p}"
        assert "segment" in p, f"preset missing 'segment': {p}"
        assert "parameters" in p, f"preset missing 'parameters': {p}"


def test_load_presets_result_types():
    presets = load_presets()
    tree_presets = [p for p in presets if p["result_type"] == "tree"]
    table_presets = [p for p in presets if p["result_type"] == "table"]
    assert len(tree_presets) == 1, "expected 1 tree preset"
    assert len(table_presets) == 4, "expected 4 table presets"


def test_load_presets_table_presets_have_cypher():
    for p in load_presets():
        if p["result_type"] == "table":
            assert "cypher_template" in p, f"table preset '{p['id']}' missing cypher_template"


def test_load_presets_ids_unique():
    ids = [p["id"] for p in load_presets()]
    assert len(ids) == len(set(ids)), "preset ids are not unique"


def test_load_presets_coaching_tree_present():
    ids = {p["id"] for p in load_presets()}
    assert "coaching_tree" in ids


def test_load_presets_known_ids():
    ids = {p["id"] for p in load_presets()}
    expected = {
        "coaching_tree",
        "sec_defensive_coordinators",
        "oc_hire_context",
        "staff_stability",
        "coaching_path",
    }
    assert ids == expected


# ---------------------------------------------------------------------------
# _resolve_coach_code
# ---------------------------------------------------------------------------


def test_resolve_coach_code_found_via_direct_name():
    record = {"mc_code": 42}
    mock_rec = MagicMock()
    mock_rec.get = MagicMock(side_effect=record.get)

    driver = MagicMock()
    session = MagicMock()
    session.run.return_value.single.return_value = mock_rec
    driver.session.return_value.__enter__ = MagicMock(return_value=session)
    driver.session.return_value.__exit__ = MagicMock(return_value=False)

    result = _resolve_coach_code("Nick Saban", driver)
    assert result == 42


def test_resolve_coach_code_not_found_returns_none():
    driver = MagicMock()
    session = MagicMock()
    session.run.return_value.single.return_value = None
    driver.session.return_value.__enter__ = MagicMock(return_value=session)
    driver.session.return_value.__exit__ = MagicMock(return_value=False)

    result = _resolve_coach_code("Unknown Coach", driver)
    assert result is None


def test_resolve_coach_code_single_word_name_returns_none():
    driver = MagicMock()
    result = _resolve_coach_code("Saban", driver)
    assert result is None
    driver.session.assert_not_called()


# ---------------------------------------------------------------------------
# _build_tree_rows
# ---------------------------------------------------------------------------


def test_build_tree_rows_basic():
    raw = [
        {
            "name": "Kirby Smart",
            "coach_code": 101,
            "depth": 1,
            "path_coaches": ["Nick Saban", "Kirby Smart"],
            "confidence_flag": "STANDARD",
        },
    ]
    role_map = {101: "HC"}
    name_to_code = {"Kirby Smart": 101}
    depth1_codes = {101}

    rows = _build_tree_rows(raw, "Nick Saban", role_map, depth1_codes, name_to_code)
    assert len(rows) == 1
    assert rows[0].display_name == "Kirby Smart"
    assert rows[0].depth == 1
    assert rows[0].role == "HC"
    assert rows[0].confidence_flag == "STANDARD"
    assert rows[0].mentor_coach_id is None  # depth-1 mentor is root


def test_build_tree_rows_depth2_wired_to_mentor():
    raw = [
        {
            "name": "Kirby Smart",
            "coach_code": 101,
            "depth": 1,
            "path_coaches": ["Nick Saban", "Kirby Smart"],
            "confidence_flag": "STANDARD",
        },
        {
            "name": "Dan Lanning",
            "coach_code": 202,
            "depth": 2,
            "path_coaches": ["Nick Saban", "Kirby Smart", "Dan Lanning"],
            "confidence_flag": None,
        },
    ]
    role_map = {101: "HC", 202: "HC"}
    name_to_code = {"Kirby Smart": 101, "Dan Lanning": 202}
    depth1_codes = {101}

    rows = _build_tree_rows(raw, "Nick Saban", role_map, depth1_codes, name_to_code)
    assert len(rows) == 2
    lanning = next(r for r in rows if r.display_name == "Dan Lanning")
    assert lanning.mentor_coach_id == 101
    assert lanning.depth == 2


def test_build_tree_rows_orphan_depth2_filtered():
    """Depth-2 node whose mentor is not in depth-1 set should be dropped."""
    raw = [
        {
            "name": "Dan Lanning",
            "coach_code": 202,
            "depth": 2,
            "path_coaches": ["Nick Saban", "Ghost Coach", "Dan Lanning"],
            "confidence_flag": None,
        },
    ]
    role_map = {}
    name_to_code = {"Dan Lanning": 202}
    depth1_codes = set()  # no depth-1 coaches

    rows = _build_tree_rows(raw, "Nick Saban", role_map, depth1_codes, name_to_code)
    assert rows == []


def test_build_tree_rows_deduplicates():
    raw = [
        {"name": "Kirby Smart", "coach_code": 101, "depth": 1,
         "path_coaches": ["Nick Saban", "Kirby Smart"], "confidence_flag": None},
        {"name": "Kirby Smart", "coach_code": 101, "depth": 1,
         "path_coaches": ["Nick Saban", "Kirby Smart"], "confidence_flag": None},
    ]
    rows = _build_tree_rows(raw, "Nick Saban", {101: "HC"}, {101}, {"Kirby Smart": 101})
    assert len(rows) == 1


# ---------------------------------------------------------------------------
# _run_tree_preset
# ---------------------------------------------------------------------------


def test_run_tree_preset_coach_not_found():
    driver = MagicMock()
    session = MagicMock()
    session.run.return_value.single.return_value = None
    driver.session.return_value.__enter__ = MagicMock(return_value=session)
    driver.session.return_value.__exit__ = MagicMock(return_value=False)

    preset = {"id": "coaching_tree", "name": "Coaching Tree", "result_type": "tree", "parameters": []}
    result = _run_tree_preset(preset, {"coach_name": "Unknown Person"}, driver)

    assert result.error != ""
    assert result.grag_result is None


def test_run_tree_preset_empty_coach_name():
    driver = MagicMock()
    preset = {"id": "coaching_tree", "name": "Coaching Tree", "result_type": "tree", "parameters": []}
    result = _run_tree_preset(preset, {"coach_name": ""}, driver)

    assert "required" in result.error.lower()
    driver.session.assert_not_called()


def test_run_tree_preset_returns_grag_result_on_success():
    # First session.run call: _resolve_coach_code
    mc_record = MagicMock()
    mc_record.get = lambda k, default=None: 99 if k == "mc_code" else default

    # get_coaching_tree returns one depth-1 row
    tree_row = {
        "name": "Kirby Smart",
        "coach_code": 101,
        "depth": 1,
        "path_coaches": ["Nick Saban", "Kirby Smart"],
        "confidence_flag": "STANDARD",
    }

    # get_best_roles returns one row
    role_row = {"coach_code": 101, "role": "HC"}

    driver = MagicMock()
    session = MagicMock()
    # Call sequence: resolve_coach_code, get_coaching_tree, get_best_roles
    session.run.side_effect = [
        MagicMock(single=MagicMock(return_value=mc_record)),   # resolve
        iter([tree_row]),                                        # get_coaching_tree
        iter([role_row]),                                        # get_best_roles
    ]
    driver.session.return_value.__enter__ = MagicMock(return_value=session)
    driver.session.return_value.__exit__ = MagicMock(return_value=False)

    preset = {"id": "coaching_tree", "name": "Coaching Tree", "result_type": "tree", "parameters": []}
    result = _run_tree_preset(preset, {"coach_name": "Nick Saban"}, driver)

    assert result.error == ""
    assert result.result_type == "tree"
    assert result.grag_result is not None
    assert result.grag_result.intent == "TREE_QUERY"
    assert result.root_name == "Nick Saban"


# ---------------------------------------------------------------------------
# _run_table_preset
# ---------------------------------------------------------------------------


def test_run_table_preset_returns_rows():
    rows_data = [
        {"coach_name": "Steve Sarkisian", "team": "Alabama", "season": 2020},
    ]
    driver = MagicMock()
    session = MagicMock()
    session.run.return_value = iter(rows_data)
    driver.session.return_value.__enter__ = MagicMock(return_value=session)
    driver.session.return_value.__exit__ = MagicMock(return_value=False)

    preset = {
        "id": "sec_defensive_coordinators",
        "name": "Conference DCs",
        "result_type": "table",
        "cypher_template": "MATCH (c:Coach) RETURN c.name AS coach_name",
        "columns": [{"key": "coach_name", "label": "Coach"}],
        "answer_template": "{count} results.",
    }
    result = _run_table_preset(preset, {"conference": "SEC", "season": 2020}, driver)

    assert result.result_type == "table"
    assert result.error == ""
    assert len(result.rows) == 1
    assert result.rows[0]["coach_name"] == "Steve Sarkisian"
    assert result.answer == "1 results."


def test_run_table_preset_computed_params():
    """computed_params should expand prev_season = season - 1 before Cypher."""
    driver = MagicMock()
    session = MagicMock()
    session.run.return_value = iter([])
    driver.session.return_value.__enter__ = MagicMock(return_value=session)
    driver.session.return_value.__exit__ = MagicMock(return_value=False)

    preset = {
        "id": "staff_stability",
        "name": "Staff Stability",
        "result_type": "table",
        "cypher_template": "MATCH (t) RETURN t",
        "computed_params": [{"name": "prev_season", "expr": "season - 1"}],
        "columns": [],
    }
    _run_table_preset(preset, {"conference": "SEC", "season": 2024}, driver)

    call_kwargs = session.run.call_args
    assert call_kwargs[1].get("prev_season") == 2023


def test_run_table_preset_empty_result():
    driver = MagicMock()
    session = MagicMock()
    session.run.return_value = iter([])
    driver.session.return_value.__enter__ = MagicMock(return_value=session)
    driver.session.return_value.__exit__ = MagicMock(return_value=False)

    preset = {
        "id": "test",
        "name": "Test",
        "result_type": "table",
        "cypher_template": "RETURN 1",
        "columns": [],
    }
    result = _run_table_preset(preset, {}, driver)
    assert result.rows == []
    assert result.error == ""


# ---------------------------------------------------------------------------
# run_preset (dispatch + error handling)
# ---------------------------------------------------------------------------


def test_run_preset_dispatches_tree():
    preset = {"id": "coaching_tree", "name": "Tree", "result_type": "tree", "parameters": []}
    with patch("presets.runner._run_tree_preset") as mock_tree:
        mock_tree.return_value = PresetResult(result_type="tree", preset_id="coaching_tree", preset_name="Tree")
        driver = MagicMock()
        run_preset(preset, {"coach_name": "Nick Saban"}, driver)
        mock_tree.assert_called_once()


def test_run_preset_dispatches_table():
    preset = {
        "id": "sec_dcs", "name": "SEC DCs", "result_type": "table",
        "cypher_template": "MATCH (c) RETURN c", "parameters": [],
    }
    with patch("presets.runner._run_table_preset") as mock_table:
        mock_table.return_value = PresetResult(result_type="table", preset_id="sec_dcs", preset_name="SEC DCs")
        driver = MagicMock()
        run_preset(preset, {"conference": "SEC", "season": 2024}, driver)
        mock_table.assert_called_once()


def test_run_preset_returns_error_on_exception():
    preset = {"id": "bad", "name": "Bad Preset", "result_type": "table", "parameters": []}
    driver = MagicMock()
    driver.session.side_effect = RuntimeError("connection failed")

    result = run_preset(preset, {}, driver)
    assert result.error != ""
    assert result.preset_id == "bad"
