"""Level 2 end-to-end tests (ADR-007).

Nine tests covering:
  1. CS+R template backward compatibility (matches CS_RESISTOR_TEMPLATE)
  2. SF standalone template backward compatibility (matches SF_RESISTOR_TEMPLATE)
  3. CS+ICS template backward compatibility (matches CS_IDEAL_CURRENT_SOURCE_TEMPLATE)
  4. CS+R numerical execution: composed template gives same results as hand-written
  5. CS+R SPICE cross-check: composed circuit → ngspice → |error| < 5%
  6. Two-stage CS+R→SF numerical: Av_total≈-2.03, loading_factor=1.0 (L2.6)
  7. Two-stage random feasibility: 30 seeds, all sat_ok=1.0 (L2.6)
  8. Two-stage SPICE cross-check: composed 2-stage circuit → ngspice (L2.6)
  9. Three-stage random feasibility: 20 seeds, no exceptions (L2.6)
"""

from __future__ import annotations

from pathlib import Path

import pytest

from src.solver.dag_executor import DAGNode, execute_reasoning_dag
from src.solver.template_generator import generate_template
from src.solver.templates import (
    CS_IDEAL_CURRENT_SOURCE_TEMPLATE,
    CS_RESISTOR_TEMPLATE,
    SF_RESISTOR_TEMPLATE,
)
from src.topology.compositor import compose_stages
from src.topology.random_compositor import generate_composed_circuit
from src.topology.stage_library import (
    CS_CORE,
    CS_CORE_ICS,
    CURRENT_SOURCE_LOAD,
    RESISTOR_LOAD,
    SF_CORE,
)
from tests.golden_helpers import build_model_params, load_golden

GOLDEN_PATH = Path("tests/golden/golden_cs_resistor_load.yaml")
TOLERANCE = 0.05


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _dag_to_tuples(nodes: list[DAGNode]) -> list[tuple]:
    return [
        (n.id, n.step, n.rule_name, tuple(n.input_ids), n.output_symbol)
        for n in nodes
    ]


def _rel_err(actual: float, expected: float) -> float:
    import math
    if math.isinf(expected) and math.isinf(actual) and (expected > 0) == (actual > 0):
        return 0.0
    return abs(actual - expected) / abs(expected)


def _assert_close(actual: float, expected: float, label: str) -> None:
    err = _rel_err(actual, expected)
    assert err <= TOLERANCE, (
        f"{label}: expected {expected:.6g}, got {actual:.6g}, "
        f"relative error {err:.1%} > {TOLERANCE:.0%}"
    )


# ---------------------------------------------------------------------------
# Test 1: CS+R template backward compatibility
# ---------------------------------------------------------------------------

def test_cs_r_template_backward_compat() -> None:
    """generate_template(CS_CORE, RESISTOR_LOAD) must equal CS_RESISTOR_TEMPLATE."""
    generated = generate_template(CS_CORE, RESISTOR_LOAD)
    assert _dag_to_tuples(generated) == _dag_to_tuples(CS_RESISTOR_TEMPLATE), (
        "Generated CS+R template differs from CS_RESISTOR_TEMPLATE.\n"
        f"Generated: {[n.id for n in generated]}\n"
        f"Expected:  {[n.id for n in CS_RESISTOR_TEMPLATE]}"
    )


# ---------------------------------------------------------------------------
# Test 2: SF standalone template backward compatibility
# ---------------------------------------------------------------------------

def test_sf_standalone_template_backward_compat() -> None:
    """generate_template(SF_CORE) must equal SF_RESISTOR_TEMPLATE."""
    generated = generate_template(SF_CORE)
    assert _dag_to_tuples(generated) == _dag_to_tuples(SF_RESISTOR_TEMPLATE), (
        "Generated SF standalone template differs from SF_RESISTOR_TEMPLATE.\n"
        f"Generated: {[n.id for n in generated]}\n"
        f"Expected:  {[n.id for n in SF_RESISTOR_TEMPLATE]}"
    )


# ---------------------------------------------------------------------------
# Test 3: CS+ICS template backward compatibility
# ---------------------------------------------------------------------------

def test_cs_ics_template_backward_compat() -> None:
    """generate_template(CS_CORE_ICS, CURRENT_SOURCE_LOAD) must equal CS_IDEAL_CURRENT_SOURCE_TEMPLATE."""
    generated = generate_template(CS_CORE_ICS, CURRENT_SOURCE_LOAD)
    assert _dag_to_tuples(generated) == _dag_to_tuples(CS_IDEAL_CURRENT_SOURCE_TEMPLATE), (
        "Generated CS+ICS template differs from CS_IDEAL_CURRENT_SOURCE_TEMPLATE.\n"
        f"Generated: {[n.id for n in generated]}\n"
        f"Expected:  {[n.id for n in CS_IDEAL_CURRENT_SOURCE_TEMPLATE]}"
    )


# ---------------------------------------------------------------------------
# Test 4: CS+R numerical execution (composed template gives same results)
# ---------------------------------------------------------------------------

def test_cs_r_numerical_execution() -> None:
    """Executing the composed CS+R template yields the same final_values as the hand-written template."""
    golden = load_golden(GOLDEN_PATH)
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

    hand_trace = execute_reasoning_dag(CS_RESISTOR_TEMPLATE, given)
    composed_template = generate_template(CS_CORE, RESISTOR_LOAD)
    composed_trace = execute_reasoning_dag(composed_template, given)

    for key in ("VGS", "VOV", "ID", "VD", "VDS", "gm", "ro", "Rout", "Av", "Cout", "p1_Hz"):
        _assert_close(
            composed_trace.final_values[key],
            hand_trace.final_values[key],
            f"final_values[{key!r}]",
        )


# ---------------------------------------------------------------------------
# Test 5: CS+R SPICE cross-check via composed circuit
# ---------------------------------------------------------------------------

@pytest.mark.spice
def test_cs_r_spice_crosscheck() -> None:
    """Compose CS+R circuit via compose_stages → SPICE → compare ID and gm within 5%."""
    from src.solver.spice_runner import run_spice
    from src.utils.netlist_writer import circuit_to_netlist

    golden = load_golden(GOLDEN_PATH)
    g = golden["given"]
    given = {
        "VDD":     float(g["VDD"]),
        "RD":      float(g["RD"]),
        "VG_DC":   float(g["VG_DC"]),
        "Vth":     float(g["Vth"]),
        "mun_Cox": float(g["mun_Cox"]),
        "W":       float(g["W"]),
        "L":       float(g["L"]),
        "lambda":  float(g["lambda"]),
        "CL":      float(g["CL"]),
        "Cgd":     float(g["Cgd"]),
        "kn":      float(g["mun_Cox"]) * (float(g["W"]) / float(g["L"])),
    }

    circuit = compose_stages(
        instances=[("cs", CS_CORE), ("load", RESISTOR_LOAD)],
        interconnections=[("cs.vout", "load.load_bot")],
        given=given,
        sample_id="level2_e2e_spice",
    )

    model_params = build_model_params(given)
    netlist = circuit_to_netlist(circuit, model_params=model_params)
    result = run_spice(netlist, analysis="op")

    exp = golden["expected"]
    tol = golden["tolerance"]

    assert "m1" in result.device_parameters, (
        f"ngspice did not report m1 parameters. Nodes: {list(result.node_voltages)}"
    )
    m1 = result.device_parameters["m1"]

    exp_id = float(exp["qpoint"]["ID"])
    assert _rel_err(m1["id"], exp_id) < tol, (
        f"m1.id: got {m1['id']:.4g}, expected {exp_id:.4g}"
    )

    exp_gm = float(exp["small_signal"]["gm"])
    assert _rel_err(m1["gm"], exp_gm) < tol, (
        f"m1.gm: got {m1['gm']:.4g}, expected {exp_gm:.4g}"
    )


# ---------------------------------------------------------------------------
# Test 6: Two-stage CS+R → SF numerical (L2.6)
# ---------------------------------------------------------------------------

def test_two_stage_cs_sf_numerical() -> None:
    """Two-stage CS+R → SF: loading_factor=1.0 (infinite gate Rin) and Av_total≈-2.03."""
    given = {
        "VDD":        5.0,
        # Stage 1: CS+R  (VOV=0.7 → Av_s1=-2.8)
        "VG_DC_s1":   1.2,
        "Vth_s1":     0.5,
        "kn_s1":      1e-3,
        "lambda_s1":  0.0,
        "RD_s1":      4000.0,
        # Stage 2: SF  (quadratic solve → Av_s2≈0.723)
        "VG_DC_s2":   2.0,
        "Vth_s2":     0.5,
        "kn_s2":      2e-3,
        "lambda_s2":  0.0,
        "Rs_load_s2": 2000.0,
        "CL":         1e-12,
        "Cgd":        0.1e-12,
    }
    template = generate_template([(CS_CORE, RESISTOR_LOAD), (SF_CORE, None)])
    trace = execute_reasoning_dag(template, given)
    fv = trace.final_values

    assert fv["sat_ok_s1"] == 1.0, f"Stage 1 not in saturation: VDS={fv.get('VDS_s1')}"
    assert fv["sat_ok_s2"] == 1.0, f"Stage 2 not in saturation: VDS={fv.get('VDS_s2')}"

    # SF gate has infinite Rin → loading factor must be exactly 1.0
    assert fv["loading_factor_s1_s2"] == pytest.approx(1.0, abs=1e-9), (
        f"loading_factor_s1_s2 expected 1.0, got {fv['loading_factor_s1_s2']}"
    )

    # Av_total = Av_s1 * Av_s2 = -2.8 * 0.7227 ≈ -2.024
    assert fv["Av_total"] == pytest.approx(-2.03, rel=0.02), (
        f"Av_total expected ≈-2.03, got {fv['Av_total']:.4f}"
    )

    # Av_total_dB must be consistent with Av_total
    import math
    assert fv["Av_total_dB"] == pytest.approx(20 * math.log10(abs(fv["Av_total"])), rel=0.001)


# ---------------------------------------------------------------------------
# Test 7: Two-stage random feasibility (L2.6)
# ---------------------------------------------------------------------------

def test_two_stage_random_feasibility() -> None:
    """generate_composed_circuit(num_stages=2) must produce sat_ok=1.0 for 30 seeds."""
    for seed in range(30):
        result = generate_composed_circuit(seed=seed, num_stages=2)
        trace = execute_reasoning_dag(result.template, result.given)
        fv = trace.final_values

        assert fv.get("sat_ok_s1") == 1.0, (
            f"seed={seed} stage_keys={result.stage_keys}: "
            f"Stage 1 not in saturation (sat_ok_s1={fv.get('sat_ok_s1')})"
        )
        assert fv.get("sat_ok_s2") == 1.0, (
            f"seed={seed} stage_keys={result.stage_keys}: "
            f"Stage 2 not in saturation (sat_ok_s2={fv.get('sat_ok_s2')})"
        )


# ---------------------------------------------------------------------------
# Test 8: Two-stage SPICE cross-check (L2.6)
# ---------------------------------------------------------------------------

@pytest.mark.spice
def test_two_stage_spice_crosscheck() -> None:
    """Two-stage CS+R → SF: node voltages from SPICE match DAG within 20%.

    Stage 1 (CS+R): VD_s1 from SPICE ≈ VD_s1 from DAG.
    Stage 2 (SF):   VS_s2 from SPICE ≈ VS_s2 from DAG.
    Node voltages are more reliably extracted from ngspice than per-device
    operating-point blocks, which may be absent for multi-device circuits.
    """
    from src.solver.spice_runner import run_spice
    from src.utils.netlist_writer import circuit_to_netlist

    # Both stages use the same MOSFET model (mun_Cox=1e-4, W=10μm, L=1μm → kn=1e-3)
    given = {
        "VDD":        5.0,
        # Stage 1: CS+R  (VOV=0.7V, DAG VD≈4.02V; SPICE with CLM ≈ 3.66V)
        "VG_DC_s1":   1.2,
        "Vth_s1":     0.5,
        "kn_s1":      1e-3,
        "lambda_s1":  0.1,
        "RD_s1":      4000.0,
        # Stage 2: SF  (quadratic solve → ID≈80μA, DAG VS≈0.8V; SPICE ≈ 0.85V)
        "VG_DC_s2":   1.7,
        "Vth_s2":     0.5,
        "kn_s2":      1e-3,
        "lambda_s2":  0.1,
        "Rs_load_s2": 10000.0,
        # Shared
        "CL":         1e-12,
        "Cgd":        0.1e-12,
        "W":          10e-6,
        "L":          1e-6,
        # SPICE model (single NMOS model for both transistors)
        "mun_Cox":    1e-4,
        "Vth":        0.5,
        "lambda":     0.1,
    }

    instances = [
        ("sig_s1", CS_CORE), ("load_s1", RESISTOR_LOAD),
        ("sig_s2", SF_CORE),
    ]
    interconnections = [("sig_s1.vout", "load_s1.load_bot")]
    circuit = compose_stages(
        instances, interconnections, given,
        sample_id="2stage_spice", stage_indices=[1, 1, 2]
    )

    model_params = build_model_params(given)
    netlist = circuit_to_netlist(circuit, model_params=model_params)
    spice_result = run_spice(netlist, analysis="op")

    # DAG reference values (lambda ignored at Q-point per ADR-003)
    template = generate_template([(CS_CORE, RESISTOR_LOAD), (SF_CORE, None)])
    trace = execute_reasoning_dag(template, given)
    fv = trace.final_values

    SPICE_TOL = 0.20

    node_v = spice_result.node_voltages

    # Stage 1: drain node = CS transistor drain = VDD - ID_s1 * RD_s1
    assert "drain" in node_v, (
        f"ngspice did not report 'drain' node. Nodes: {list(node_v)}"
    )
    assert _rel_err(node_v["drain"], fv["VD_s1"]) < SPICE_TOL, (
        f"Stage-1 VD: spice={node_v['drain']:.4g}, dag={fv['VD_s1']:.4g}"
    )

    # Stage 2: source node = SF transistor source = ID_s2 * Rs_load_s2
    assert "source" in node_v, (
        f"ngspice did not report 'source' node. Nodes: {list(node_v)}"
    )
    assert _rel_err(node_v["source"], fv["VS_s2"]) < SPICE_TOL, (
        f"Stage-2 VS: spice={node_v['source']:.4g}, dag={fv['VS_s2']:.4g}"
    )


# ---------------------------------------------------------------------------
# Test 9: Three-stage random feasibility (L2.6)
# ---------------------------------------------------------------------------

def test_three_stage_random_feasibility() -> None:
    """generate_composed_circuit(num_stages=3) must not raise for 20 seeds."""
    for seed in range(20):
        result = generate_composed_circuit(seed=seed, num_stages=3)
        trace = execute_reasoning_dag(result.template, result.given)
        fv = trace.final_values

        for stage_idx in range(1, len(result.stage_keys) + 1):
            key = f"sat_ok_s{stage_idx}"
            assert fv.get(key) == 1.0, (
                f"seed={seed} stage_keys={result.stage_keys}: "
                f"Stage {stage_idx} not in saturation ({key}={fv.get(key)})"
            )
