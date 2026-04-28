"""Multi-topology generator tests (Phase 2 Task 6).

Covers:
  • Determinism — same seed → identical (circuit, given)
  • Feasibility — DAG saturation check passes for 20 seeds per topology
  • Variance — generate_random_circuit hits ≥ 4 topologies in 50 draws
  • Pipeline e2e — generate_and_solve_sample with explicit topology key
"""

import math

import pytest

from src.solver.dag_executor import execute_reasoning_dag
from src.solver.templates import (
    CASCODE_RESISTOR_TEMPLATE,
    CG_RESISTOR_TEMPLATE,
    CS_IDEAL_CURRENT_SOURCE_TEMPLATE,
    SF_RESISTOR_TEMPLATE,
)
from src.topology.generator import (
    generate_cascode_resistor_circuit,
    generate_cg_resistor_circuit,
    generate_cs_current_source_circuit,
    generate_random_circuit,
    generate_sf_resistor_circuit,
)
from src.packager.pipeline import generate_and_solve_sample


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _all_finite(given: dict[str, float]) -> bool:
    return all(math.isfinite(v) and not math.isnan(v) for v in given.values())


# ---------------------------------------------------------------------------
# Determinism
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("gen_fn", [
    generate_sf_resistor_circuit,
    generate_cs_current_source_circuit,
    generate_cg_resistor_circuit,
    generate_cascode_resistor_circuit,
])
def test_generator_deterministic(gen_fn):
    c1, g1 = gen_fn(seed=42)
    c2, g2 = gen_fn(seed=42)
    assert c1 == c2, f"{gen_fn.__name__}: same seed must produce identical Circuit"
    assert g1 == g2, f"{gen_fn.__name__}: same seed must produce identical given dict"


def test_random_circuit_deterministic():
    c1, g1, t1 = generate_random_circuit(seed=7)
    c2, g2, t2 = generate_random_circuit(seed=7)
    assert t1 == t2
    assert c1 == c2
    assert g1 == g2


# ---------------------------------------------------------------------------
# SF feasibility
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("seed", range(20))
def test_sf_resistor_feasibility(seed):
    _, given = generate_sf_resistor_circuit(seed=seed)
    assert _all_finite(given), f"SF seed={seed}: non-finite value in given"
    trace = execute_reasoning_dag(SF_RESISTOR_TEMPLATE, given)
    assert trace.final_values["sat_ok"] == 1.0, (
        f"SF seed={seed}: saturation check failed "
        f"(VDS={trace.final_values.get('VDS'):.4f}, VOV={trace.final_values.get('VOV'):.4f})"
    )


# ---------------------------------------------------------------------------
# CS + ideal current source feasibility
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("seed", range(20))
def test_cs_ics_feasibility(seed):
    _, given = generate_cs_current_source_circuit(seed=seed)
    assert _all_finite(given), f"CS+ICS seed={seed}: non-finite value in given"
    trace = execute_reasoning_dag(CS_IDEAL_CURRENT_SOURCE_TEMPLATE, given)
    assert trace.final_values["sat_ok"] == 1.0, (
        f"CS+ICS seed={seed}: saturation check failed"
    )


# ---------------------------------------------------------------------------
# CG feasibility
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("seed", range(20))
def test_cg_resistor_feasibility(seed):
    _, given = generate_cg_resistor_circuit(seed=seed)
    assert _all_finite(given), f"CG seed={seed}: non-finite value in given"
    trace = execute_reasoning_dag(CG_RESISTOR_TEMPLATE, given)
    assert trace.final_values["sat_ok"] == 1.0, (
        f"CG seed={seed}: saturation check failed"
    )


# ---------------------------------------------------------------------------
# Cascode feasibility
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("seed", range(20))
def test_cascode_resistor_feasibility(seed):
    _, given = generate_cascode_resistor_circuit(seed=seed)
    assert _all_finite(given), f"Cascode seed={seed}: non-finite value in given"
    trace = execute_reasoning_dag(CASCODE_RESISTOR_TEMPLATE, given)
    assert trace.final_values["sat_ok1"] == 1.0, (
        f"Cascode seed={seed}: M1 saturation check failed"
    )
    assert trace.final_values["sat_ok2"] == 1.0, (
        f"Cascode seed={seed}: M2 saturation check failed"
    )


# ---------------------------------------------------------------------------
# generate_random_circuit topology variance
# ---------------------------------------------------------------------------

def test_random_circuit_topology_variance():
    topologies: set[str] = set()
    for seed in range(50):
        _, _, topo_key = generate_random_circuit(seed=seed)
        topologies.add(topo_key)
    assert len(topologies) >= 4, (
        f"generate_random_circuit hit only {len(topologies)} topologies in 50 draws: "
        f"{topologies}"
    )


# ---------------------------------------------------------------------------
# Pipeline e2e — one topology per key (no SPICE to keep tests fast)
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("topo_key", [
    "cs_resistor",
    "sf_resistor",
    "cs_current_source",
    "cg_resistor",
    "cascode_resistor",
])
def test_pipeline_topology_e2e(topo_key, tmp_path):
    sample_dir = generate_and_solve_sample(
        seed=0,
        output_dir=tmp_path,
        run_spice_check=False,
        topology=topo_key,
    )
    assert sample_dir.exists(), f"{topo_key}: sample_dir not created"
    assert (sample_dir / "problem.json").exists(), f"{topo_key}: problem.json missing"
    assert (sample_dir / "solution.json").exists(), f"{topo_key}: solution.json missing"
    assert (sample_dir / "traces.jsonl").exists(),  f"{topo_key}: traces.jsonl missing"

    import json
    problem = json.loads((sample_dir / "problem.json").read_text())
    assert problem["topology"] == topo_key, (
        f"problem.json topology mismatch: expected '{topo_key}', got '{problem['topology']}'"
    )


def test_pipeline_random_topology_e2e(tmp_path):
    sample_dir = generate_and_solve_sample(
        seed=42,
        output_dir=tmp_path,
        run_spice_check=False,
        topology=None,
    )
    assert sample_dir.exists()

    import json
    problem = json.loads((sample_dir / "problem.json").read_text())
    from src.topology.generator import _TOPOLOGY_KEYS
    assert problem["topology"] in _TOPOLOGY_KEYS, (
        f"random topology '{problem['topology']}' not in _TOPOLOGY_KEYS"
    )


def test_pipeline_unknown_topology_raises():
    with pytest.raises(ValueError, match="Unknown topology"):
        generate_and_solve_sample(topology="nonexistent_topo")
