"""Sample serializer: writes one sample's outputs to the §7 file layout.

See docs/design_notes.md §7 for the canonical file structure.
"""

import dataclasses
import json
import math
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from src.solver.dag_executor import ReasoningTrace
from src.solver.spice_runner import SpiceResult
from src.topology.models import Circuit
from src.utils.model_params import build_model_params
from src.utils.netlist_writer import circuit_to_netlist


# Per-quantity tolerances for DAG vs SPICE cross-check.
# Node voltages are tightly constrained by KVL (5%).
# Small-signal parameters have systematic deviation between hand-calc
# Level-1 equations and ngspice's internal model extraction (relaxed to 20%).
VALIDATION_TOLERANCES: dict[str, float] = {
    "VD": 0.05,   # node voltage: strict
    "ID": 0.20,   # drain current: relaxed
    "gm": 0.20,   # transconductance: relaxed
}

# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def serialize_sample(
    sample_dir: Path,
    circuit: Circuit,
    given: dict[str, float],
    trace: ReasoningTrace,
    spice_result: SpiceResult | None = None,
    tolerance: float = 0.05,
) -> Path:
    """Write all sample artefacts to sample_dir.

    Creates the directory if it does not exist. Files written:
      circuit.json    — Circuit pydantic model (JSON)
      circuit.cir     — SPICE netlist text
      problem.json    — given parameters + question metadata
      traces.jsonl    — ReasoningTrace entries, one JSON object per line
      solution.json   — structured answer extracted from trace.final_values
      validation.log  — DAG vs SPICE cross-check (only if spice_result given)

    Returns: sample_dir
    """
    sample_dir.mkdir(parents=True, exist_ok=True)

    _write_circuit_json(sample_dir / "circuit.json", circuit)
    _write_circuit_cir(sample_dir / "circuit.cir", circuit, given)
    _write_problem_md(sample_dir / "problem.md")
    _write_problem_json(sample_dir / "problem.json", circuit, given)
    _write_solution_md(sample_dir / "solution.md")
    _write_traces_jsonl(sample_dir / "traces.jsonl", trace)
    _write_solution_json(sample_dir / "solution.json", circuit, trace)
    if spice_result is not None:
        _write_validation_log(
            sample_dir / "validation.log",
            trace.final_values,
            spice_result,
            circuit.sample_id,
        )

    return sample_dir


# ---------------------------------------------------------------------------
# Per-file writers
# ---------------------------------------------------------------------------

def _write_circuit_json(path: Path, circuit: Circuit) -> None:
    path.write_text(circuit.model_dump_json(indent=2))


def _write_problem_md(path: Path) -> None:
    path.write_text(
        "# Problem\n\n"
        "TODO: human-readable problem statement (Phase 2)\n\n"
        "See problem.json for machine-readable version.\n"
    )


def _write_solution_md(path: Path) -> None:
    path.write_text(
        "# Solution\n\n"
        "TODO: human-readable solution following template.md format (Phase 2)\n\n"
        "See solution.json and traces.jsonl for machine-readable version.\n"
    )


def _write_circuit_cir(
    path: Path, circuit: Circuit, given: dict[str, float]
) -> None:
    netlist = circuit_to_netlist(circuit, model_params=build_model_params(given))
    path.write_text(netlist)


def _write_problem_json(
    path: Path, circuit: Circuit, given: dict[str, float]
) -> None:
    doc = {
        "sample_id": circuit.sample_id,
        "topology": "nmos_common_source_resistor_load",
        "given": given,
        "question_type": "qpoint",
        "asked_quantities": ["VGS", "VOV", "ID", "VD", "VDS", "gm", "Av"],
    }
    path.write_text(json.dumps(doc, indent=2))


def _write_traces_jsonl(path: Path, trace: ReasoningTrace) -> None:
    lines = []
    for entry in trace.entries:
        raw = dataclasses.asdict(entry)
        lines.append(json.dumps(_sanitize_for_json(raw)))
    path.write_text("\n".join(lines) + "\n")


def _write_solution_json(
    path: Path, circuit: Circuit, trace: ReasoningTrace
) -> None:
    fv = trace.final_values
    doc = {
        "sample_id": circuit.sample_id,
        "qpoint": {
            "VGS": fv.get("VGS"),
            "VOV": fv.get("VOV"),
            "ID":  fv.get("ID"),
            "VD":  fv.get("VD"),
            "VDS": fv.get("VDS"),
        },
        "small_signal": {
            "gm": fv.get("gm"),
            "ro": fv.get("ro"),
        },
        "low_frequency": {
            "Av":     fv.get("Av"),
            "Rout":   fv.get("Rout"),
            "Av_dB":  fv.get("Av_dB"),
        },
        "high_frequency": {
            "Cout":    fv.get("Cout"),
            "p1_omega": fv.get("p1_omega"),
            "p1_Hz":   fv.get("p1_Hz"),
        },
    }
    path.write_text(json.dumps(_sanitize_for_json(doc), indent=2))


def _write_validation_log(
    path: Path,
    final_values: dict[str, float],
    spice_result: SpiceResult,
    sample_id: str,
) -> None:
    ts = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    m1 = spice_result.device_parameters.get("m1", {})

    comparisons: list[tuple[str, float | None, float | None]] = [
        ("VD", final_values.get("VD"), spice_result.node_voltages.get("vo")),
        ("ID", final_values.get("ID"), _abs_or_none(m1.get("id"))),
        ("gm", final_values.get("gm"), m1.get("gm")),
    ]

    lines = [f"sample_id: {sample_id}", f"timestamp: {ts}", ""]
    has_fail = False

    for name, dag_val, spice_val in comparisons:
        if dag_val is None or spice_val is None:
            lines.append(f"{name}: dag=N/A, spice=N/A, rel_err=N/A, SKIP")
            continue
        ref = abs(dag_val)
        if ref == 0.0:
            lines.append(f"{name}: dag={dag_val:.6g}, spice={spice_val:.6g}, rel_err=N/A, SKIP")
            continue
        err = abs(dag_val - spice_val) / ref
        tol = VALIDATION_TOLERANCES.get(name, 0.05)
        if err < tol:
            verdict = "PASS"
        elif err < 0.20:
            verdict = "WARNING"
        else:
            verdict = "FAIL"
            has_fail = True
        lines.append(
            f"{name}: dag={dag_val:.6g}, spice={spice_val:.6g}, "
            f"rel_err={err:.2%}, {verdict}"
        )

    lines.append(f"OVERALL: {'FAIL' if has_fail else 'PASS'}")
    path.write_text("\n".join(lines) + "\n")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _sanitize_for_json(obj: Any) -> Any:
    """Recursively replace inf/nan floats with None for JSON compatibility."""
    if isinstance(obj, float) and (math.isinf(obj) or math.isnan(obj)):
        return None
    if isinstance(obj, dict):
        return {k: _sanitize_for_json(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_sanitize_for_json(v) for v in obj]
    return obj


def _abs_or_none(val: float | None) -> float | None:
    return abs(val) if val is not None else None
