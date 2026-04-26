"""Tests for src/topology/generator.py — CS + resistor load random generator."""

import math

import pytest

from src.solver.dag_executor import execute_reasoning_dag
from src.solver.templates import CS_RESISTOR_TEMPLATE
from src.topology.generator import generate_cs_resistor_circuit
from src.utils.netlist_writer import circuit_to_netlist
from src.solver.spice_runner import run_spice
from tests.golden_helpers import build_model_params


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _feasibility_params(given: dict[str, float]) -> tuple[float, float, float, float]:
    """Return (VOV, VD, VDS, VGS) derived from a given dict."""
    VGS = given["VG_DC"]
    VOV = VGS - given["Vth"]
    ID  = 0.5 * given["kn"] * VOV ** 2
    VD  = given["VDD"] - ID * given["RD"]
    VDS = VD  # grounded source
    return VOV, VD, VDS, VGS


# ---------------------------------------------------------------------------
# Test 1: determinism
# ---------------------------------------------------------------------------

def test_generate_cs_resistor_deterministic():
    circuit_a, given_a = generate_cs_resistor_circuit(seed=42)
    circuit_b, given_b = generate_cs_resistor_circuit(seed=42)

    assert circuit_a == circuit_b, "same seed must produce identical Circuit"
    assert given_a   == given_b,   "same seed must produce identical given dict"


# ---------------------------------------------------------------------------
# Test 2: feasibility over 50 seeds
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("seed", range(50))
def test_generate_cs_resistor_feasibility(seed):
    _, given = generate_cs_resistor_circuit(seed=seed)

    VOV, VD, VDS, VGS = _feasibility_params(given)

    assert VGS > given["Vth"], \
        f"seed={seed}: MOSFET in cutoff — VGS={VGS:.4f} ≤ Vth={given['Vth']:.4f}"
    assert VDS >= VOV, \
        f"seed={seed}: MOSFET in triode — VDS={VDS:.4f} < VOV={VOV:.4f}"
    assert VD > 0.0, \
        f"seed={seed}: drain pulled to ground — VD={VD:.4f}"
    assert VD < given["VDD"], \
        f"seed={seed}: drain above supply — VD={VD:.4f} ≥ VDD={given['VDD']:.4f}"

    for key, val in given.items():
        assert math.isfinite(val) and not math.isnan(val), \
            f"seed={seed}: given['{key}'] = {val} is not a finite number"


# ---------------------------------------------------------------------------
# Test 3: variance across 20 seeds
# ---------------------------------------------------------------------------

def test_generate_cs_resistor_variance():
    VDD_values = set()
    RD_values  = set()

    for seed in range(20):
        _, given = generate_cs_resistor_circuit(seed=seed)
        VDD_values.add(round(given["VDD"], 4))
        RD_values.add(round(given["RD"], 1))

    assert len(VDD_values) >= 3, \
        f"VDD has insufficient variance — only {len(VDD_values)} distinct values"
    assert len(RD_values) >= 3, \
        f"RD has insufficient variance — only {len(RD_values)} distinct values"


# ---------------------------------------------------------------------------
# Test 4: DAG compatibility
# ---------------------------------------------------------------------------

def test_generate_cs_resistor_dag_compatible():
    _, given = generate_cs_resistor_circuit(seed=7)
    trace = execute_reasoning_dag(CS_RESISTOR_TEMPLATE, given)
    assert trace.final_values["sat_ok"] == 1.0, \
        "DAG saturation check failed for generated circuit"


# ---------------------------------------------------------------------------
# Test 5: SPICE compatibility
# ---------------------------------------------------------------------------

@pytest.mark.spice
def test_generate_cs_resistor_spice_compatible():
    circuit, given = generate_cs_resistor_circuit(seed=99)

    netlist = circuit_to_netlist(circuit, model_params=build_model_params(given))
    result  = run_spice(netlist, analysis="op")

    assert "vo" in result.node_voltages, \
        "ngspice output missing 'vo' node voltage"
    assert result.node_voltages["vo"] > 0.0, \
        f"vo = {result.node_voltages['vo']:.4f} V — drain pulled to ground"
