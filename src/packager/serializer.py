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
    topology: str = "nmos_common_source_resistor_load",
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
    _write_problem_json(sample_dir / "problem.json", circuit, given, topology)
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
    netlist = circuit_to_netlist(circuit, model_params=build_model_params(given, circuit=circuit))
    path.write_text(netlist)


def _write_problem_json(
    path: Path, circuit: Circuit, given: dict[str, float],
    topology: str = "nmos_common_source_resistor_load",
) -> None:
    doc = {
        "sample_id": circuit.sample_id,
        "topology": topology,
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

    if "Av_total" in fv:
        # Multi-stage: per-stage breakdown + cascade summary
        stage_idx = 1
        stages: dict = {}
        while f"sat_ok_s{stage_idx}" in fv:
            s = f"_s{stage_idx}"
            stages[f"stage_{stage_idx}"] = {
                "qpoint": {
                    "VGS": fv.get(f"VGS{s}"),
                    "VOV": fv.get(f"VOV{s}"),
                    "ID":  fv.get(f"ID{s}"),
                    "VD":  fv.get(f"VD{s}") if fv.get(f"VD{s}") is not None else fv.get(f"VS{s}"),
                    "VDS": fv.get(f"VDS{s}"),
                },
                "small_signal": {"gm": fv.get(f"gm{s}"), "ro": fv.get(f"ro{s}")},
                "gain": {"Av": fv.get(f"Av{s}"), "Rout": fv.get(f"Rout{s}")},
                "sat_ok": fv.get(f"sat_ok{s}"),
            }
            stage_idx += 1
        doc = {
            "sample_id": circuit.sample_id,
            "cascade": {
                "Av_total":    fv.get("Av_total"),
                "Av_total_dB": fv.get("Av_total_dB"),
            },
            "stages": stages,
        }
    else:
        # Single-stage: original structure
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
                "Cout":     fv.get("Cout"),
                "p1_omega": fv.get("p1_omega"),
                "p1_Hz":    fv.get("p1_Hz"),
            },
        }
    path.write_text(json.dumps(_sanitize_for_json(doc), indent=2))


def _compare_one(
    name: str,
    dag_val: float | None,
    spice_val: float | None,
) -> tuple[str, bool]:
    """Return (log_line, is_fail) for one DAG-vs-SPICE comparison."""
    if dag_val is None or spice_val is None:
        return f"{name}: dag=N/A, spice=N/A, rel_err=N/A, SKIP", False
    ref = abs(dag_val)
    if ref == 0.0:
        return f"{name}: dag={dag_val:.6g}, spice={spice_val:.6g}, rel_err=N/A, SKIP", False
    err = abs(dag_val - spice_val) / ref
    tol = VALIDATION_TOLERANCES.get(name, 0.05)
    if err < tol:
        verdict = "PASS"
    elif err < 0.20:
        verdict = "WARNING"
    else:
        verdict = "FAIL"
    return (
        f"{name}: dag={dag_val:.6g}, spice={spice_val:.6g}, rel_err={err:.2%}, {verdict}",
        verdict == "FAIL",
    )


def _write_validation_log(
    path: Path,
    final_values: dict[str, float],
    spice_result: SpiceResult,
    sample_id: str,
) -> None:
    ts = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    log_lines = [f"sample_id: {sample_id}", f"timestamp: {ts}", ""]
    has_fail = False

    if "Av_total" in final_values:
        # Multi-stage: compare ID and gm per stage
        stage_idx = 1
        while f"ID_s{stage_idx}" in final_values or f"gm_s{stage_idx}" in final_values:
            dev_key = "m1" if stage_idx == 1 else f"m1_sig_s{stage_idx}"
            m = spice_result.device_parameters.get(dev_key, {})
            log_lines.append(f"--- stage {stage_idx} ({dev_key}) ---")
            for qty, dag_key, spice_fn in [
                ("ID", f"ID_s{stage_idx}", lambda m=m: _abs_or_none(m.get("id"))),
                ("gm", f"gm_s{stage_idx}", lambda m=m: m.get("gm")),
            ]:
                line, fail = _compare_one(qty, final_values.get(dag_key), spice_fn())
                log_lines.append(line)
                has_fail = has_fail or fail
            stage_idx += 1
    else:
        # Single-stage
        m1 = spice_result.device_parameters.get("m1", {})
        for qty, dag_key, spice_val in [
            ("VD", "VD", spice_result.node_voltages.get("vo")),
            ("ID", "ID", _abs_or_none(m1.get("id"))),
            ("gm", "gm", m1.get("gm")),
        ]:
            line, fail = _compare_one(qty, final_values.get(dag_key), spice_val)
            log_lines.append(line)
            has_fail = has_fail or fail

    log_lines.append(f"OVERALL: {'FAIL' if has_fail else 'PASS'}")
    path.write_text("\n".join(log_lines) + "\n")


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
