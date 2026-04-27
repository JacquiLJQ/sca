"""Three-layer reasoning DAG integration tests — CG + resistor load.

No golden YAML for CG; expected values are hand-calculated and hardcoded.

Given parameters:
  VDD=1.8, RD=10000, VG_bias=1.0, Vin_DC=0.3, Vth=0.5,
  kn=1e-3 (mun_Cox=100e-6, W=1e-6, L=1e-7 → W/L=10),
  lambda=0, CL=100e-15, Cgd=5e-15

Hand-calculated expected values:
  VGS  = VG_bias - Vin_DC = 1.0 - 0.3 = 0.7
  VOV  = VGS - Vth = 0.7 - 0.5 = 0.2
  ID   = 0.5 * 1e-3 * 0.2² = 20e-6
  VD   = VDD - ID*RD = 1.8 - 0.2 = 1.6
  VDS  = VD - Vin_DC = 1.6 - 0.3 = 1.3  (saturation: VDS >= VOV ✓)
  gm   = kn * VOV = 2e-4
  ro   = inf  (lambda = 0)
  Rout = RD || ro = 10000
  Av   = +gm * Rout = +2.0  (non-inverting)
  Rin  = 1/gm = 5000
  Cout = CL + Cgd*(1 - 1/Av) = 100e-15 + 5e-15*0.5 = 102.5e-15
  p1   = 1/(Rout*Cout) = 9.756e8 rad/s → 1.553e8 Hz
"""

import math

import pytest

from src.solver.dag_executor import STEP_NAMES, ReasoningTrace, execute_reasoning_dag
from src.solver.templates import CG_RESISTOR_TEMPLATE

TOLERANCE = 0.05
CANONICAL_STEP_NAMES = set(STEP_NAMES.values())

_GIVEN: dict[str, float] = {
    "VDD":     1.8,
    "VG_bias": 1.0,
    "Vin_DC":  0.3,
    "Vth":     0.5,
    "kn":      1e-3,
    "lambda":  0.0,
    "RD":      10_000.0,
    "CL":      100e-15,
    "Cgd":     5e-15,
}

_EXP: dict[str, float] = {
    "VGS":    0.7,
    "VOV":    0.2,
    "ID":     20e-6,
    "VD":     1.6,
    "VDS":    1.3,
    "gm":     2e-4,
    "Rout":   10_000.0,
    "Av":     2.0,
    "Av_dB":  20.0 * math.log10(2.0),
    "Rin":    5_000.0,
    "Cout":   102.5e-15,
    "p1_Hz":  1.553e8,
}


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
def dag_trace() -> ReasoningTrace:
    return execute_reasoning_dag(CG_RESISTOR_TEMPLATE, _GIVEN)


# ---------------------------------------------------------------------------
# Q-point (Step 3)
# ---------------------------------------------------------------------------

def test_qpoint_VGS(dag_trace):
    _assert_close(dag_trace.final_values["VGS"], _EXP["VGS"], "VGS")


def test_qpoint_VOV(dag_trace):
    _assert_close(dag_trace.final_values["VOV"], _EXP["VOV"], "VOV")


def test_qpoint_ID(dag_trace):
    _assert_close(dag_trace.final_values["ID"], _EXP["ID"], "ID")


def test_qpoint_VD(dag_trace):
    _assert_close(dag_trace.final_values["VD"], _EXP["VD"], "VD")


def test_qpoint_VDS(dag_trace):
    _assert_close(dag_trace.final_values["VDS"], _EXP["VDS"], "VDS")


# ---------------------------------------------------------------------------
# Saturation verification (Step 4)
# ---------------------------------------------------------------------------

def test_saturation_check_passes(dag_trace):
    assert dag_trace.final_values["sat_ok"] == 1.0


# ---------------------------------------------------------------------------
# Small-signal parameters (Step 5)
# ---------------------------------------------------------------------------

def test_small_signal_gm(dag_trace):
    _assert_close(dag_trace.final_values["gm"], _EXP["gm"], "gm")


def test_small_signal_ro_infinite(dag_trace):
    assert math.isinf(dag_trace.final_values["ro"]), "ro must be inf when lambda=0"


# ---------------------------------------------------------------------------
# Low-frequency analysis (Step 6)
# ---------------------------------------------------------------------------

def test_low_freq_Rout(dag_trace):
    _assert_close(dag_trace.final_values["Rout"], _EXP["Rout"], "Rout")


def test_low_freq_Av_positive(dag_trace):
    assert dag_trace.final_values["Av"] > 0, "CG gain must be positive (non-inverting)"
    _assert_close(dag_trace.final_values["Av"], _EXP["Av"], "Av")


def test_low_freq_Av_dB(dag_trace):
    _assert_close(dag_trace.final_values["Av_dB"], _EXP["Av_dB"], "Av_dB")


def test_low_freq_Rin(dag_trace):
    _assert_close(dag_trace.final_values["Rin"], _EXP["Rin"], "Rin")


# ---------------------------------------------------------------------------
# High-frequency capacitance (Step 7)
# ---------------------------------------------------------------------------

def test_high_freq_Cout(dag_trace):
    _assert_close(dag_trace.final_values["Cout"], _EXP["Cout"], "Cout")


# ---------------------------------------------------------------------------
# Poles (Step 8)
# ---------------------------------------------------------------------------

def test_pole_p1_Hz(dag_trace):
    _assert_close(dag_trace.final_values["p1_Hz"], _EXP["p1_Hz"], "p1_Hz")


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
    missing = _GIVEN.keys() - dag_trace.final_values.keys()
    assert not missing, f"given keys missing from final_values: {missing}"


def test_trace_length_matches_template(dag_trace):
    assert len(dag_trace.entries) == len(CG_RESISTOR_TEMPLATE)
