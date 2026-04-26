"""Three-layer reasoning DAG integration tests — Case 1 (CS + resistor load).

Verifies that CS_RESISTOR_TEMPLATE + execute_reasoning_dag + rules.py
produce values matching golden_cs_resistor_load.yaml within 5% tolerance
(ADR-003). Also validates trace-level metadata invariants from ADR-006.
"""

import math
from pathlib import Path

import pytest

from src.solver.dag_executor import STEP_NAMES, ReasoningTrace, execute_reasoning_dag
from src.solver.templates import CS_RESISTOR_TEMPLATE
from tests.golden_helpers import load_golden

GOLDEN_PATH = Path("tests/golden/golden_cs_resistor_load.yaml")
TOLERANCE = 0.05
CANONICAL_STEP_NAMES = set(STEP_NAMES.values())


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _rel_err(actual: float, expected: float) -> float:
    return abs(actual - expected) / abs(expected)


def _assert_close(actual: float, expected: float, label: str) -> None:
    err = _rel_err(actual, expected)
    assert err <= TOLERANCE, (
        f"{label}: expected {expected:.6g}, got {actual:.6g}, "
        f"relative error {err:.1%} > {TOLERANCE:.0%}"
    )


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture(scope="module")
def golden() -> dict:
    return load_golden(GOLDEN_PATH)


@pytest.fixture(scope="module")
def dag_trace(golden) -> ReasoningTrace:
    g = golden["given"]
    kn = float(g["mun_Cox"]) * (float(g["W"]) / float(g["L"]))
    given = {
        "VDD":    float(g["VDD"]),
        "RD":     float(g["RD"]),
        "VG_DC":  float(g["VG_DC"]),
        "Vth":    float(g["Vth"]),
        "kn":     kn,
        "lambda": float(g["lambda"]),
        "CL":     float(g["CL"]),
        "Cgd":    float(g["Cgd"]),
    }
    return execute_reasoning_dag(CS_RESISTOR_TEMPLATE, given)


# ---------------------------------------------------------------------------
# Q-point (Step 3)
# ---------------------------------------------------------------------------

def test_qpoint_VGS(dag_trace, golden):
    _assert_close(
        dag_trace.final_values["VGS"],
        float(golden["expected"]["qpoint"]["VGS"]),
        "VGS",
    )


def test_qpoint_VOV(dag_trace, golden):
    _assert_close(
        dag_trace.final_values["VOV"],
        float(golden["expected"]["qpoint"]["VOV"]),
        "VOV",
    )


def test_qpoint_ID(dag_trace, golden):
    _assert_close(
        dag_trace.final_values["ID"],
        float(golden["expected"]["qpoint"]["ID"]),
        "ID",
    )


def test_qpoint_VD(dag_trace, golden):
    _assert_close(
        dag_trace.final_values["VD"],
        float(golden["expected"]["qpoint"]["VD"]),
        "VD",
    )


# ---------------------------------------------------------------------------
# Saturation verification (Step 4)
# ---------------------------------------------------------------------------

def test_saturation_check_passes(dag_trace, golden):
    assert golden["expected"]["qpoint"]["saturation_check_passes"] is True
    assert dag_trace.final_values["sat_ok"] == 1.0


# ---------------------------------------------------------------------------
# Small-signal parameters (Step 5)
# ---------------------------------------------------------------------------

def test_small_signal_gm(dag_trace, golden):
    _assert_close(
        dag_trace.final_values["gm"],
        float(golden["expected"]["small_signal"]["gm"]),
        "gm",
    )


def test_small_signal_ro_infinite_when_lambda_zero(dag_trace, golden):
    if golden["expected"]["small_signal"]["ro"] is None:
        assert math.isinf(dag_trace.final_values["ro"]), (
            "ro must be float('inf') when lambda=0"
        )


# ---------------------------------------------------------------------------
# Low-frequency analysis (Step 6)
# ---------------------------------------------------------------------------

def test_low_freq_Rout(dag_trace, golden):
    _assert_close(
        dag_trace.final_values["Rout"],
        float(golden["expected"]["low_frequency"]["Rout"]),
        "Rout",
    )


def test_low_freq_Av(dag_trace, golden):
    _assert_close(
        dag_trace.final_values["Av"],
        float(golden["expected"]["low_frequency"]["Av"]),
        "Av",
    )


def test_low_freq_Av_dB(dag_trace, golden):
    _assert_close(
        dag_trace.final_values["Av_dB"],
        float(golden["expected"]["low_frequency"]["Av_dB"]),
        "Av_dB",
    )


# ---------------------------------------------------------------------------
# High-frequency capacitance (Step 7)
# ---------------------------------------------------------------------------

def test_high_freq_Cout(dag_trace, golden):
    _assert_close(
        dag_trace.final_values["Cout"],
        float(golden["expected"]["high_frequency"]["Cout_total"]),
        "Cout",
    )


# ---------------------------------------------------------------------------
# Poles (Step 8)
# ---------------------------------------------------------------------------

def test_pole_p1_Hz(dag_trace, golden):
    _assert_close(
        dag_trace.final_values["p1_Hz"],
        float(golden["expected"]["high_frequency"]["p1_Hz"]),
        "p1_Hz",
    )


# ---------------------------------------------------------------------------
# Trace metadata invariants (ADR-006)
# ---------------------------------------------------------------------------

def test_all_trace_entries_have_justification(dag_trace):
    for entry in dag_trace.entries:
        assert entry.justification, (
            f"node '{entry.node_id}' (rule '{entry.rule_name}') has empty justification"
        )


def test_all_trace_entries_have_formula_latex(dag_trace):
    for entry in dag_trace.entries:
        assert entry.formula_latex, (
            f"node '{entry.node_id}' (rule '{entry.rule_name}') has empty formula_latex"
        )


def test_all_step_names_are_canonical(dag_trace):
    for entry in dag_trace.entries:
        assert entry.step_name in CANONICAL_STEP_NAMES, (
            f"node '{entry.node_id}' has unrecognised step_name '{entry.step_name}'"
        )


# ---------------------------------------------------------------------------
# Structural completeness
# ---------------------------------------------------------------------------

def test_final_values_contains_all_given_keys(dag_trace):
    expected_keys = {"VDD", "RD", "VG_DC", "Vth", "kn", "lambda", "CL", "Cgd"}
    missing = expected_keys - dag_trace.final_values.keys()
    assert not missing, f"given keys missing from final_values: {missing}"


def test_trace_length_matches_template(dag_trace):
    assert len(dag_trace.entries) == len(CS_RESISTOR_TEMPLATE)
