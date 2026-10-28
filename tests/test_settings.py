"""Settings: defaults, user overrides, validation and the provisional storage in the case configuration."""

from __future__ import annotations

import importlib.util
import json
import math

import pytest

from _paths import delivered

SPEC = importlib.util.spec_from_file_location("gridlens_settings", delivered("main.py"))
gl = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(gl)

PERIOD = (0.0, 30 * 24 * 3600.0)


@pytest.fixture(autouse=True)
def defaults():
    gl.reset_settings()
    yield
    gl.reset_settings()


@pytest.fixture
def editor():
    records = [{"key": "P\\FS1", "id": "FS1", "name": "FS1", "window": (0.0, 3600.0), "component_keys": ["P\\L1"],
                "equipment_name": "Line L1", "start_time": "", "end_time": "", "priority": 1, "originally_ignored": False}]
    config = gl.empty_case_config()
    config["cases"] = [{"id": "C1", "name": "Summer", "outages": ["P\\FS1"]}]
    return gl.CaseEditor(records, config, PERIOD)


def test_defaults_are_the_values_of_the_existing_code():
    values = gl.default_settings()

    assert values["line_warning"] == values["transformer_warning"] == gl.LOADING_WARNING == 80.0
    assert values["line_limit"] == values["transformer_limit"] == gl.LOADING_MAX == 100.0
    assert not any(key.startswith("band") for key in values), "one voltage band in p.u. for every level"
    assert (values["voltage_min_pu"], values["voltage_max_pu"]) == (0.95, 1.05)
    assert values["energized_min_pu"] == gl.ENERGIZED_MIN_PU and values["top_n"] == gl.TOP_N == 10
    assert values["max_plot_points"] == gl.MAX_PLOT_POINTS and values["max_cases"] == gl.MAX_CASES
    assert values["max_n1_times"] == gl.MAX_N1_TIMES and values["run_reference"] is gl.RUN_REFERENCE_CASE
    assert (values["loading_appendix_delta"], values["voltage_appendix_delta"]) == (
        gl.LOADING_APPENDIX_DELTA, gl.VOLTAGE_APPENDIX_DELTA)
    assert values["loading_change_tolerance"] == gl.LOADING_DELTA_TOLERANCE == 0.1
    assert values["voltage_change_tolerance"] == gl.VOLTAGE_DELTA_TOLERANCE == 0.001
    assert values["n1_limit_mode"] == gl.N1_LIMITS_POWERFACTORY


def test_voltage_proposal_and_sources_are_labelled():
    assert "proposal" in gl.SETTINGS_BY_KEY["voltage_min_pu"]["note"]
    assert "proposal" in gl.SETTINGS_BY_KEY["voltage_max_pu"]["note"]
    assert gl.setting_source("line_limit") == gl.SOURCE_GRIDLENS
    assert gl.setting_source("line_limit", {"line_limit": 110.0}) == gl.SOURCE_USER
    assert gl.setting_source("contingency_set") == gl.SOURCE_POWERFACTORY


def test_calculation_parameters_are_category_b_and_read_only():
    calculation = [setting for setting in gl.SETTINGS if setting["category"] == gl.CATEGORY_CALCULATION]

    assert {setting["key"] for setting in calculation} >= {"contingency_set", "post_fault_phases", "remedial_actions",
                                                            "islanding", "unsupplied_load", "calculation_method"}
    # Only the two n-1 filters can be edited: the n-1 run applies them via "Not analysed".
    assert [setting["key"] for setting in calculation if setting["editable"]] == ["contingency_grids", "contingency_elements"]
    value, problem = gl.parse_setting("contingency_set", "all lines")
    assert value is None and "read only" in problem
    assert all(gl.setting_help(setting["key"]).count("Category B") == 1 for setting in calculation)


@pytest.mark.parametrize("key, text, expected", [
    ("line_limit", "110", 110.0), ("line_limit", " 105,5 ", 105.5), ("voltage_min_pu", "0.9", 0.9),
    ("numeric_tolerance", "1e-6", 1e-6), ("limit_tolerance_loading", "0", 0.0), ("line_limit", 120, 120.0),
    ("n1_limit_mode", "global", "global"),
])
def test_valid_entries(key, text, expected):
    assert gl.parse_setting(key, text) == (expected, None)


@pytest.mark.parametrize("key, text, fragment", [
    ("line_limit", "abc", "finite number"), ("line_limit", "nan", "finite number"), ("line_limit", "inf", "finite number"),
    ("line_limit", "", "finite number"), ("line_limit", True, "finite number"), ("line_limit", math.nan, "finite number"),
    ("line_limit", "0", "greater than 0"), ("voltage_max_pu", "-1", "greater than 0"), ("top_n", "2.5", "whole number"),
    ("max_cases", "99", "from 1 to 20"), ("run_reference", "yes", "choose one of on, off"),
    ("worsened_tolerance_loading", "-0.1", "must not be negative"), ("n1_limit_mode", "maybe", "choose one of"),
    ("unknown", "1", "unknown setting"),
])
def test_invalid_entries_explain_themselves(key, text, fragment):
    value, problem = gl.parse_setting(key, text)

    assert value is None and fragment in problem


def test_cross_checks():
    problems = dict(gl.validate_settings({"voltage_min_pu": 1.1, "line_warning": 120.0}))

    assert "must be below" in problems["voltage_min_pu"]
    assert "must be below" in dict(gl.validate_settings({"energized_min_pu": 0.99}))["energized_min_pu"]
    assert "must not exceed" in problems["line_warning"]
    assert gl.validate_settings({}) == []
    assert gl.validate_settings("110") == [("settings", "settings must be an object of overrides")]
    with pytest.raises(gl.GridLensError, match="cannot be used"):
        gl.effective_settings({"line_limit": -5})


def test_overrides_keep_only_real_changes():
    assert gl.clean_overrides(dict(gl.default_settings(), line_limit=110.0)) == {"line_limit": 110.0}
    assert gl.clean_overrides(gl.default_settings()) == {}
    assert gl.overrides_text({}) == "GridLens defaults, no user override"
    assert "GridLens default 100 %" in gl.overrides_text({"line_limit": 110.0})


def test_snapshot_is_fixed_once_and_names_versions_and_sources():
    overrides = {"line_limit": 110.0}
    snapshot = gl.settings_snapshot(overrides)
    overrides["line_limit"] = 130.0

    assert snapshot["values"]["line_limit"] == 110.0, "a later change does not reach the snapshot"
    assert snapshot["sources"]["line_limit"] == gl.SOURCE_USER and snapshot["sources"]["line_warning"] == gl.SOURCE_GRIDLENS
    assert snapshot["settings_version"] == gl.SETTINGS_VERSION and snapshot["classification_version"] == "1.0"
    parameters = snapshot["calculation_parameters"]
    assert parameters.pop("contingency_grids") == gl.SAME_AS_ASSESSMENT + " (stored, not applied yet)"
    assert parameters.pop("contingency_elements") == "every element (stored, not applied yet)"
    assert set(parameters.values()) == {gl.NOT_VERIFIED}
    assert snapshot["storage"].startswith("provisional")


def test_activated_settings_drive_the_n0_limits_and_reset_restores_them():
    gl.activate_settings({"line_limit": 120.0, "transformer_limit": 90.0, "voltage_min_pu": 0.9, "voltage_max_pu": 1.1,
                          "top_n": 5, "run_reference": False})

    assert gl.loading_limit("line") == 120.0 and gl.loading_limit("transformer") == 90.0
    assert gl.excess({"category": "line"}, 125.0) == pytest.approx(5.0)
    assert gl.voltage_band(220.0) == gl.voltage_band(20.0) == (0.9, 1.1), "the same band for every level"
    assert gl.setting_value("top_n") == 5 and gl.setting_value("run_reference") is False
    gl.reset_settings()
    assert gl.loading_limit("line") == 100.0 and gl.voltage_band(20.0) == (0.95, 1.05)
    assert gl.setting_value("top_n") == 10 and gl.setting_value("run_reference") is True


def test_settings_are_stored_with_the_cases_and_do_not_touch_them(tmp_path, editor):
    path = str(tmp_path / "cases.json")
    cases_before = json.loads(json.dumps(editor.config["cases"]))
    assert editor.set_settings({"line_limit": "110", "line_warning": "80"}) == []
    gl.save_case_config(path, editor.config, "operator")

    with open(path, encoding="utf-8") as handle:
        stored = json.load(handle)
    loaded = gl.load_case_config(path)
    assert stored["settings"] == {"line_limit": 110.0} and "mode" not in stored
    assert loaded["settings"] == {"line_limit": 110.0}
    assert loaded["cases"] == cases_before, "existing case assignments stay unchanged"
    assert gl.resolve_request(loaded, editor.records, PERIOD)["settings"] == {"line_limit": 110.0}


def test_invalid_saved_settings_are_refused_with_the_reason(tmp_path):
    config = gl.empty_case_config()
    config["settings"] = {"line_limit": -1}

    assert any(problem.startswith("settings: ") for problem in gl.validate_case_config(config))
    with pytest.raises(gl.GridLensError, match="not saved"):
        gl.save_case_config(str(tmp_path / "cases.json"), config)


def test_a_file_of_an_earlier_version_with_mode_still_loads(tmp_path):
    config = gl.empty_case_config()
    config["mode"] = "optimized"
    path = tmp_path / "cases.json"
    path.write_text(json.dumps(config), encoding="utf-8")

    loaded = gl.load_case_config(str(path))
    assert "mode" not in gl.CaseEditor([], loaded, PERIOD).config


def test_editor_refuses_invalid_settings_and_restores_defaults(editor):
    problems = editor.set_settings({"line_limit": "abc", "voltage_min_pu": "0.9"})

    assert problems and problems[0][0] == "line_limit"
    assert editor.settings_overrides() == {}, "nothing changes while one entry is invalid"
    assert editor.set_settings({"voltage_min_pu": "1.2"})[0][0] == "voltage_min_pu"
    assert editor.set_settings({"voltage_min_pu": "0.9"}) == []
    assert editor.settings_overrides() == {"voltage_min_pu": 0.9}
    rows = {row[0]: row for row in editor.settings_rows()}
    assert rows["voltage_min_pu"][4] == gl.SOURCE_USER and rows["line_limit"][4] == gl.SOURCE_GRIDLENS
    assert rows["contingency_set"][3] == gl.NOT_VERIFIED and rows["contingency_set"][6] is False
    assert "Settings" in dict(editor.summary()[0])
    assert "Settings: Minimum voltage, every voltage level = 0.9 p.u." in editor.calculation_preview()
    editor.restore_default_settings()
    assert editor.settings_overrides() == {}


def test_every_setting_has_a_hover_text():
    for setting in gl.SETTINGS:
        text = gl.setting_help(setting["key"])
        assert len(text) > 40 and "Applies to" in text, setting["key"]
    for key in ("restore_defaults", "apply_settings", "save_settings", "classification", "limits"):
        assert gl.SETTING_HELP[key]
    assert "not yet into the PowerFactory project" in gl.SETTING_HELP["save_settings"]


def test_qds_time_base_is_read_only_information():
    lines = dict(gl.qds_time_info(None, (1467331200.0, 1467417600.0)))

    assert set(lines) == {"QDS start", "QDS end", "QDS time step", "Time definition", "Calculated period"}
    assert "nothing is shortened" in lines["Calculated period"]

    class Qds:
        calcPeriod, stepSize, stepUnit = 0, 2, 1

    stepped = dict(gl.qds_time_info(Qds(), (1467331200.0, 1467417600.0)))
    assert "stepSize] = 2" in stepped["QDS time step"]


def test_the_case_limit_follows_the_setting(editor):
    assert gl.case_limit(editor.config) == gl.MAX_CASES == 5
    assert editor.set_settings({"max_cases": "2"}) == []
    assert gl.case_limit(editor.config) == 2
    editor.add_case("A")
    assert editor.limit_problem() is not None and "Settings" in editor.limit_problem()
    too_many = dict(editor.config, cases=editor.config["cases"] + [{"id": "C9", "name": "x", "outages": []}])
    assert any("at most 2 planning cases" in problem for problem in gl.validate_case_config(too_many))


def test_the_results_choice_offers_the_kept_runs_and_reaches_the_request(editor):
    editor.kept_stamps = ["261023-120000", "261022-080000"]
    choices = editor.result_choices()
    assert choices[0] == (gl.RESULTS_CALCULATE, None)
    assert choices[1] == ("Re-evaluate the kept run of 2026-10-23 12:00:00", "261023-120000")
    assert editor.set_evaluate_stamp("999999-000000") is not None and editor.evaluate_stamp is None
    assert editor.set_evaluate_stamp("261023-120000") is None
    assert editor.request()["evaluate_stamp"] == "261023-120000"
    assert "Results: Re-evaluate the kept run of 2026-10-23 12:00:00 (no calculation)" in editor.calculation_preview()
    assert "evaluate_stamp" not in editor.config, "the choice is never saved with the cases"
