"""Three-layer reasoning DAG integration tests — Cascode + resistor load.

No golden YAML; expected values are hand-calculated and hardcoded.

Given parameters:
  VDD=3.3, RD=10000, Vin_DC=0.9, VG2_bias=1.5
  M1: kn1=1e-3, Vth1=0.5, lambda1=0.02
  M2: kn2=1e-3, Vth2=0.5, lambda2=0.02
  CL=100e-15, Cgd=5e-15

Hand-calculated expected values:
  VGS1 = Vin_DC = 0.9
  VOV1 = VGS1 - Vth1 = 0.4
  ID   = 0.5 * 1e-3 * 0.4² = 80e-6
  VOV2 = sqrt(2*80e-6/1e-3) = 0.4  (kn same → same VOV)
  VGS2 = VOV2 + Vth2 = 0.9
  vx   = VG2_bias - VGS2 = 1.5 - 0.9 = 0.6
  vo   = VDD - ID*RD = 3.3 - 0.8 = 2.5
  VDS1 = vx = 0.6         (M1.source = GND)  sat1: 0.6 >= 0.4 ✓
  VDS2 = vo - vx = 1.9                        sat2: 1.9 >= 0.4 ✓
  gm1 = gm2 = kn*VOV = 4e-4
  ro1 = ro2 = 1/(0.02*80e-6) = 625 kΩ
  Rout_cascode = ro2*(1 + gm2*ro1) = 625000*251 = 156.875 MΩ
  Rout_total   = RD || Rout_cascode ≈ 9999.4 Ω
  Av           = -gm1 * Rout_total ≈ -4.0
  Cout = CL + Cgd*(1 - 1/Av) = 100e-15 + 5e-15*1.25 = 106.25e-15
  p1_Hz ≈ 1.498e8 Hz
"""

import math

import pytest

from src.solver.dag_executor import STEP_NAMES, ReasoningTrace, execute_reasoning_dag
from src.solver.templates import CASCODE_RESISTOR_TEMPLATE

TOLERANCE = 0.05
CANONICAL_STEP_NAMES = set(STEP_NAMES.values())

_GIVEN: dict[str, float] = {
    "VDD":      3.3,
    "Vin_DC":   0.9,
    "VG2_bias": 1.5,
    "Vth1":     0.5,
    "Vth2":     0.5,
    "kn1":      1e-3,
    "kn2":      1e-3,
    "lambda1":  0.02,
    "lambda2":  0.02,
    "RD":       10_000.0,
    "CL":       100e-15,
    "Cgd":      5e-15,
}

# Exact hand-calculated values (used as reference for 5% tolerance checks)
_ro = 1.0 / (0.02 * 80e-6)                        # 625 000 Ω
_gm = 1e-3 * 0.4                                   # 4e-4 S
_Rout_cascode = _ro * (1.0 + _gm * _ro)
_Rout = (10_000.0 * _Rout_cascode) / (10_000.0 + _Rout_cascode)
_Av   = -_gm * _Rout
_Cout = 100e-15 + 5e-15 * (1.0 - 1.0 / _Av)
_p1_Hz = 1.0 / (2.0 * math.pi * _Rout * _Cout)

_EXP: dict[str, float] = {
    "VGS1":         0.9,
    "VOV1":         0.4,
    "ID":           80e-6,
    "VOV2":         0.4,
    "VGS2":         0.9,
    "vx":           0.6,
    "vo":           2.5,
    "VDS1":         0.6,
    "VDS2":         1.9,
    "gm1":          _gm,
    "ro1":          _ro,
    "gm2":          _gm,
    "ro2":          _ro,
    "Rout_cascode": _Rout_cascode,
    "Rout":         _Rout,
    "Av":           _Av,
    "Av_dB":        20.0 * math.log10(abs(_Av)),
    "Cout":         _Cout,
    "p1_Hz":        _p1_Hz,
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
    return execute_reasoning_dag(CASCODE_RESISTOR_TEMPLATE, _GIVEN)


# ---------------------------------------------------------------------------
# Q-point — M1 (Step 3)
# ---------------------------------------------------------------------------

def test_qpoint_VGS1(dag_trace):
    _assert_close(dag_trace.final_values["VGS1"], _EXP["VGS1"], "VGS1")


def test_qpoint_VOV1(dag_trace):
    _assert_close(dag_trace.final_values["VOV1"], _EXP["VOV1"], "VOV1")


def test_qpoint_ID(dag_trace):
    _assert_close(dag_trace.final_values["ID"], _EXP["ID"], "ID")


# ---------------------------------------------------------------------------
# Q-point — M2 and node voltages (Step 3)
# ---------------------------------------------------------------------------

def test_qpoint_VOV2(dag_trace):
    _assert_close(dag_trace.final_values["VOV2"], _EXP["VOV2"], "VOV2")


def test_qpoint_VGS2(dag_trace):
    _assert_close(dag_trace.final_values["VGS2"], _EXP["VGS2"], "VGS2")


def test_qpoint_vx(dag_trace):
    _assert_close(dag_trace.final_values["vx"], _EXP["vx"], "vx")


def test_qpoint_vo(dag_trace):
    _assert_close(dag_trace.final_values["vo"], _EXP["vo"], "vo")


def test_qpoint_VDS1(dag_trace):
    _assert_close(dag_trace.final_values["VDS1"], _EXP["VDS1"], "VDS1")


def test_qpoint_VDS2(dag_trace):
    _assert_close(dag_trace.final_values["VDS2"], _EXP["VDS2"], "VDS2")


# ---------------------------------------------------------------------------
# Saturation verification — both devices (Step 4)
# ---------------------------------------------------------------------------

def test_saturation_M1_passes(dag_trace):
    assert dag_trace.final_values["sat_ok1"] == 1.0


def test_saturation_M2_passes(dag_trace):
    assert dag_trace.final_values["sat_ok2"] == 1.0


# ---------------------------------------------------------------------------
# Small-signal parameters — both devices (Step 5)
# ---------------------------------------------------------------------------

def test_small_signal_gm1(dag_trace):
    _assert_close(dag_trace.final_values["gm1"], _EXP["gm1"], "gm1")


def test_small_signal_ro1(dag_trace):
    _assert_close(dag_trace.final_values["ro1"], _EXP["ro1"], "ro1")


def test_small_signal_gm2(dag_trace):
    _assert_close(dag_trace.final_values["gm2"], _EXP["gm2"], "gm2")


def test_small_signal_ro2(dag_trace):
    _assert_close(dag_trace.final_values["ro2"], _EXP["ro2"], "ro2")


# ---------------------------------------------------------------------------
# Low-frequency analysis (Step 6)
# ---------------------------------------------------------------------------

def test_low_freq_Rout_cascode(dag_trace):
    _assert_close(dag_trace.final_values["Rout_cascode"], _EXP["Rout_cascode"], "Rout_cascode")


def test_low_freq_Rout_total(dag_trace):
    _assert_close(dag_trace.final_values["Rout"], _EXP["Rout"], "Rout")


def test_low_freq_Av_negative(dag_trace):
    assert dag_trace.final_values["Av"] < 0, "cascode gain must be negative (inverting)"
    _assert_close(dag_trace.final_values["Av"], _EXP["Av"], "Av")


def test_low_freq_Av_dB(dag_trace):
    _assert_close(dag_trace.final_values["Av_dB"], _EXP["Av_dB"], "Av_dB")


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
    assert len(dag_trace.entries) == len(CASCODE_RESISTOR_TEMPLATE)
