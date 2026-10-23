"""classify_comparison: n-1 against (n-1)' with CLASSIFICATION_VERSION 1.0, without PowerFactory."""

from __future__ import annotations

import importlib.util
import math

import pytest

from _paths import delivered

SPEC = importlib.util.spec_from_file_location("gridlens_classification", delivered("gridlens_report.py"))
gl = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(gl)

LOADING = gl.comparison_limit("loading", values=gl.default_settings())
VOLTAGE = gl.comparison_limit("voltage", minimum=0.95, maximum=1.05)


def side(value, quantity="loading", limit=None, **fields):
    data = {"value": value, "quantity": quantity, "limit": limit or (LOADING if quantity == "loading" else VOLTAGE),
            "time": 7200.0, "contingency": "Line L3", "element": "Line L1", "phase": "post-fault"}
    data.update(fields)
    return data


def classify(reference, scenario, values=None):
    return gl.classify_comparison(reference, scenario, gl.classification_parameters(values or gl.default_settings()))


@pytest.fixture(autouse=True)
def defaults():
    gl.reset_settings()
    yield
    gl.reset_settings()


def test_codes_are_the_ten_gridlens_codes():
    assert gl.CLASSIFICATION_VERSION == "1.0"
    assert dict(gl.CLASSIFICATION_STATUSES) == {0: "OK", 1: "NEW", 2: "WORSENED", 3: "PRE_EXISTING", 4: "IMPROVED",
                                                5: "RESOLVED", 90: "FAILED", 91: "NOT_EVALUATED", 92: "NOT_APPLICABLE",
                                                93: "NOT_COMPARABLE"}


@pytest.mark.parametrize("reference, scenario, status, code", [
    (80.0, 90.0, "OK", 0),
    (85.0, 112.0, "NEW", 1),
    (105.0, 125.0, "WORSENED", 2),
    (110.0, 110.0, "PRE_EXISTING", 3),
    (120.0, 108.0, "IMPROVED", 4),
    (110.0, 95.0, "RESOLVED", 5),
])
def test_the_master_prompt_examples(reference, scenario, status, code):
    result = classify(side(reference), side(scenario))

    assert (result["status"], result["code"]) == (status, code)
    assert result["delta"] == pytest.approx(scenario - reference), "coincident delta in %-points"
    assert result["classification_version"] == "1.0"
    assert result["identity"]["time"] == 7200.0 and result["identity"]["contingency"] == "Line L3"


def test_violation_sizes_follow_the_formulas():
    assert gl.violation_size("loading", 112.0, LOADING) == pytest.approx(12.0)
    assert gl.violation_size("loading", 99.0, LOADING) == 0.0
    assert gl.violation_size("voltage", 0.93, VOLTAGE) == pytest.approx(0.02)
    assert gl.violation_size("voltage", 1.08, VOLTAGE) == pytest.approx(0.03)
    assert gl.violation_size("voltage", 1.0, VOLTAGE) == 0.0


def test_exactly_on_the_limit_is_no_violation_and_rounding_noise_neither():
    assert classify(side(90.0), side(100.0))["status"] == "OK"
    assert classify(side(90.0), side(100.0 + 1e-12))["status"] == "OK"
    assert classify(side(90.0), side(100.001))["status"] == "NEW"
    assert classify(side(1.0, "voltage"), side(1.05, "voltage"))["status"] == "OK"
    assert classify(side(1.0, "voltage"), side(0.9499, "voltage"))["status"] == "NEW"


def test_worsened_and_improved_tolerances_are_inclusive_bounds_of_pre_existing():
    # Default 0.1 %-points: a change of exactly the tolerance stays PRE_EXISTING.
    assert classify(side(110.0), side(110.1))["status"] == "PRE_EXISTING"
    assert classify(side(110.0), side(110.1001))["status"] == "WORSENED"
    assert classify(side(110.0), side(109.9))["status"] == "PRE_EXISTING"
    assert classify(side(110.0), side(109.8999))["status"] == "IMPROVED"
    assert classify(side(1.07, "voltage"), side(1.0715, "voltage"))["status"] == "WORSENED"
    assert classify(side(1.07, "voltage"), side(1.0705, "voltage"))["status"] == "PRE_EXISTING"


def test_user_tolerances_change_the_decision():
    values = dict(gl.default_settings(), worsened_tolerance_loading=5.0, improved_tolerance_loading=5.0,
                  limit_tolerance_loading=2.0)

    assert classify(side(110.0), side(114.0), values)["status"] == "PRE_EXISTING"
    assert classify(side(110.0), side(116.0), values)["status"] == "WORSENED"
    assert classify(side(110.0), side(104.0), values)["status"] == "IMPROVED"
    assert classify(side(95.0), side(101.5), values)["status"] == "OK", "within the limit tolerance"
    assert classify(side(95.0), side(102.5), values)["status"] == "NEW"


def test_failed_calculation_is_failed_and_no_violation():
    result = classify(side(90.0), side(None, state="failed", reason="load flow did not converge"))

    assert (result["status"], result["code"]) == ("FAILED", 90)
    assert result["scenario_violation"] is None and result["delta"] is None
    assert "did not converge" in result["reasons"][0]


@pytest.mark.parametrize("value", [None, math.nan, math.inf, -math.inf, True, "101.0", [101.0]])
def test_missing_or_invalid_values_are_not_evaluated_never_zero(value):
    result = classify(side(90.0), side(value))

    assert (result["status"], result["code"]) == ("NOT_EVALUATED", 91)
    assert result["delta"] is None


def test_missing_reference_value_is_not_evaluated():
    result = classify(side(None), side(105.0))

    assert result["status"] == "NOT_EVALUATED" and "n-1 reference" in result["reasons"][0]


def test_missing_limit_is_not_evaluated():
    result = classify(side(90.0, limit={"quantity": "loading"}), side(95.0, limit={"quantity": "loading"}))

    assert result["status"] == "NOT_EVALUATED" and "limit" in result["reasons"][-1]


def test_not_applicable_contingency_keeps_its_reason():
    result = classify(side(90.0), side(None, state="not_applicable", reason="Line L3 is switched off by FS1"))

    assert (result["status"], result["code"]) == ("NOT_APPLICABLE", 92)
    assert "switched off by FS1" in result["reasons"][0]


@pytest.mark.parametrize("field, other", [("time", 14400.0), ("contingency", "Line L4"), ("element", "Line L2"),
                                          ("phase", "short-term"), ("quantity", "voltage")])
def test_different_identity_is_not_comparable(field, other):
    result = classify(side(90.0), side(95.0, **{field: other}))

    assert (result["status"], result["code"]) == ("NOT_COMPARABLE", 93)
    assert field in result["reasons"][0]


def test_same_post_fault_phase_is_comparable():
    assert classify(side(90.0, phase="short-term"), side(95.0, phase="short-term"))["status"] == "OK"


def test_different_limit_definitions_are_not_comparable():
    global_limit = gl.comparison_limit("loading", values=dict(gl.default_settings(), n1_limit_mode="global",
                                                                n1_limit_global=110.0))
    result = classify(side(90.0), side(95.0, limit=global_limit))

    assert result["status"] == "NOT_COMPARABLE" and "limit definitions" in result["reasons"][0]


def test_precedence_keeps_every_reason():
    result = classify(side(None, state="failed"), side(None, state="not_applicable", time=0.0))

    assert result["status"] == "FAILED"
    assert any("not applicable" in reason for reason in result["reasons"])
    assert any("different time" in reason for reason in result["reasons"])


def test_margin_reduced_is_an_indicator_of_ok_only():
    reduced = classify(side(80.0), side(90.0))
    low = classify(side(40.0), side(60.0))
    new = classify(side(85.0), side(112.0))

    assert reduced["status"] == "OK" and reduced["indicators"] == [gl.INDICATOR_MARGIN_REDUCED]
    assert low["status"] == "OK" and low["indicators"] == [], "below the reduced-margin warning of 80 %"
    assert new["indicators"] == []
    assert classify(side(1.0, "voltage"), side(1.04, "voltage"))["indicators"] == [gl.INDICATOR_MARGIN_REDUCED]


def test_same_limit_definition_for_both_sides():
    values = gl.default_settings()
    assert gl.comparison_limit("loading", values=values) == gl.comparison_limit("loading", values=values)
    assert gl.comparison_limit("loading", values=values)["source"].startswith("PowerFactory")


def test_classification_does_not_touch_the_n0_statuses():
    item = {"category": "line", "limits": None}
    assert gl.STATUS_PREEXISTING == "PRE-EXISTING" and gl.STATUS_DEENERGIZED == "DE-ENERGISED"
    assert gl.step_status(item, 110.0, 110.0) == "PRE-EXISTING"
    assert gl.step_status({"category": "voltage", "limits": (0.95, 1.05)}, 1.0, None) == "DE-ENERGISED"


def test_pure_function_does_not_change_its_inputs():
    reference, scenario = side(105.0), side(125.0)
    before = (dict(reference), dict(scenario))

    classify(reference, scenario)

    assert (reference, scenario) == before
