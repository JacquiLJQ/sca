"""Tests for src/packager/serializer.py and src/packager/pipeline.py."""

import json
from pathlib import Path

import pytest

from src.packager.pipeline import generate_and_solve_sample
from src.packager.serializer import serialize_sample
from src.solver.dag_executor import execute_reasoning_dag
from src.solver.spice_runner import run_spice
from src.solver.templates import CS_RESISTOR_TEMPLATE
from src.topology.generator import generate_cs_resistor_circuit
from src.topology.models import Circuit
from src.utils.model_params import build_model_params
from src.utils.netlist_writer import circuit_to_netlist

_SEED = 42

EXPECTED_FILES = {
    "circuit.json",
    "circuit.cir",
    "problem.md",
    "problem.json",
    "solution.md",
    "solution.json",
    "traces.jsonl",
}
EXPECTED_FILES_WITH_SPICE = EXPECTED_FILES | {"validation.log"}


# ---------------------------------------------------------------------------
# Module-scoped fixture: serialize once without SPICE for tests 1–4
# ---------------------------------------------------------------------------

@pytest.fixture(scope="module")
def sample_dir(tmp_path_factory) -> Path:
    tmp = tmp_path_factory.mktemp("serializer")
    circuit, given = generate_cs_resistor_circuit(seed=_SEED)
    trace = execute_reasoning_dag(CS_RESISTOR_TEMPLATE, given)
    return serialize_sample(tmp / circuit.sample_id, circuit, given, trace)


@pytest.fixture(scope="module")
def circuit_and_given():
    return generate_cs_resistor_circuit(seed=_SEED)


# ---------------------------------------------------------------------------
# Test 1: all expected files are created
# ---------------------------------------------------------------------------

def test_serialize_creates_all_files(sample_dir):
    present = {p.name for p in sample_dir.iterdir()}
    assert EXPECTED_FILES <= present, (
        f"Missing files: {EXPECTED_FILES - present}"
    )


# ---------------------------------------------------------------------------
# Test 2: circuit.json roundtrip
# ---------------------------------------------------------------------------

def test_serialize_circuit_json_roundtrip(sample_dir, circuit_and_given):
    circuit, _ = circuit_and_given
    content = (sample_dir / "circuit.json").read_text()
    loaded = Circuit.model_validate_json(content)
    assert loaded.sample_id == circuit.sample_id
    assert loaded.incidence.nodes == circuit.incidence.nodes
    assert loaded.incidence.terminals == circuit.incidence.terminals


# ---------------------------------------------------------------------------
# Test 3: traces.jsonl line count matches template length
# ---------------------------------------------------------------------------

def test_serialize_traces_jsonl_line_count(sample_dir):
    lines = [l for l in (sample_dir / "traces.jsonl").read_text().splitlines() if l.strip()]
    assert len(lines) == len(CS_RESISTOR_TEMPLATE), (
        f"Expected {len(CS_RESISTOR_TEMPLATE)} trace lines, got {len(lines)}"
    )


# ---------------------------------------------------------------------------
# Test 4: solution.json has the four required sections
# ---------------------------------------------------------------------------

def test_serialize_solution_json_has_keys(sample_dir):
    doc = json.loads((sample_dir / "solution.json").read_text())
    for section in ("qpoint", "small_signal", "low_frequency", "high_frequency"):
        assert section in doc, f"solution.json missing section '{section}'"


# ---------------------------------------------------------------------------
# Test 5: validation.log overall result is PASS  (@pytest.mark.spice)
# ---------------------------------------------------------------------------

@pytest.mark.spice
def test_serialize_validation_log_pass(tmp_path):
    circuit, given = generate_cs_resistor_circuit(seed=_SEED)
    trace = execute_reasoning_dag(CS_RESISTOR_TEMPLATE, given)
    netlist = circuit_to_netlist(circuit, model_params=build_model_params(given))
    spice_result = run_spice(netlist, analysis="op")

    sample_dir = serialize_sample(
        tmp_path / circuit.sample_id,
        circuit,
        given,
        trace,
        spice_result=spice_result,
    )

    log_lines = (sample_dir / "validation.log").read_text().splitlines()
    last = log_lines[-1].strip()
    assert "FAIL" not in last, (
        f"validation.log OVERALL is FAIL — at least one quantity exceeded 20% tolerance.\n"
        f"Full log:\n" + "\n".join(log_lines)
    )


# ---------------------------------------------------------------------------
# Test 6: pipeline end-to-end  (@pytest.mark.spice)
# ---------------------------------------------------------------------------

@pytest.mark.spice
def test_pipeline_end_to_end(tmp_path):
    sample_dir = generate_and_solve_sample(seed=_SEED, output_dir=tmp_path)

    assert sample_dir.exists(), "sample_dir was not created"
    present = {p.name for p in sample_dir.iterdir()}
    assert EXPECTED_FILES_WITH_SPICE <= present, (
        f"Missing files: {EXPECTED_FILES_WITH_SPICE - present}"
    )
