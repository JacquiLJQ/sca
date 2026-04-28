from __future__ import annotations

import re
import subprocess
import tempfile
from pathlib import Path

from pydantic import BaseModel


# ---------------------------------------------------------------------------
# Exceptions
# ---------------------------------------------------------------------------

class SpiceExecutionError(RuntimeError):
    """ngspice binary could not be executed (not found, timeout, non-zero exit code)."""


class SpiceSimulationError(RuntimeError):
    """ngspice ran but simulation failed (e.g. singular matrix, no convergence)."""


# ---------------------------------------------------------------------------
# Result model
# ---------------------------------------------------------------------------

class SpiceResult(BaseModel):
    analysis: str
    node_voltages: dict[str, float]
    branch_currents: dict[str, float]
    device_parameters: dict[str, dict[str, float]]
    raw_stdout: str
    raw_stderr: str


# ---------------------------------------------------------------------------
# Private helpers: injection
# ---------------------------------------------------------------------------

def _inject_analysis(netlist: str, analysis: str) -> str:
    """Insert .{analysis} immediately before the last .end line."""
    lines = netlist.splitlines()
    for i in range(len(lines) - 1, -1, -1):
        if lines[i].strip().lower() == ".end":
            lines.insert(i, f".{analysis}")
            return "\n".join(lines)
    raise ValueError(
        "Netlist does not contain a '.end' line; cannot inject analysis. "
        "Well-formed netlists must end with .end."
    )


# ---------------------------------------------------------------------------
# Private helpers: parsing
# ---------------------------------------------------------------------------

def _is_separator(stripped: str) -> bool:
    """Return True if a stripped line is all dashes/whitespace (table separator)."""
    return bool(stripped) and re.match(r"^[-\s]+$", stripped) is not None


def _parse_node_voltages(stdout: str) -> dict[str, float]:
    """Parse the 'Node ... Voltage' table from ngspice .op stdout.

    Lines are tab-indented; values are in scientific notation.
    Returns empty dict if the section is not found.
    """
    result: dict[str, float] = {}
    in_section = False
    for line in stdout.splitlines():
        stripped = line.strip()
        if "Node" in stripped and "Voltage" in stripped:
            in_section = True
            continue
        if not in_section:
            continue
        if "Source" in stripped and "Current" in stripped:
            break
        if not stripped or _is_separator(stripped):
            continue
        parts = stripped.split()
        if len(parts) == 2:
            try:
                result[parts[0]] = float(parts[1])
            except ValueError:
                pass
    return result


def _parse_branch_currents(stdout: str) -> dict[str, float]:
    """Parse the 'Source ... Current' table from ngspice .op stdout.

    Captures all parseable key-value pairs in the section; callers
    interpret names (e.g. '#branch' suffix) for semantic meaning.
    Returns empty dict if the section is not found.
    """
    result: dict[str, float] = {}
    in_section = False
    for line in stdout.splitlines():
        stripped = line.strip()
        if "Source" in stripped and "Current" in stripped:
            in_section = True
            continue
        if not in_section:
            continue
        if re.match(r"^Mos\d+", stripped) or re.match(r"^Resistor", stripped):
            break
        if not stripped or _is_separator(stripped):
            continue
        parts = stripped.split()
        if len(parts) == 2:
            try:
                result[parts[0]] = float(parts[1])
            except ValueError:
                pass
    return result


def _parse_device_parameters(stdout: str) -> dict[str, dict[str, float]]:
    """Parse MOSFET instance parameter blocks from ngspice .op stdout.

    Handles both single-device and multi-device (multi-column) blocks:
      device   m1                       (single-device: 2 parts)
      device   m1_sig_s2   m1           (multi-device: 3+ parts)

    The first 'Mos1:' section is a model-parameter table (no 'device' row) and
    is silently skipped.  The second 'Mos1:' section is the instance-parameter
    table and contains the 'device' header row.
    """
    result: dict[str, dict[str, float]] = {}
    lines = stdout.splitlines()
    i = 0
    while i < len(lines):
        if re.match(r"^ Mos\d+:\s+", lines[i]):
            device_names: list[str] = []
            # param_name → list of float values, one per device column
            col_values: dict[str, list[float | None]] = {}
            i += 1
            while i < len(lines):
                if not lines[i].strip():
                    break
                if re.match(r"^ \w", lines[i]):
                    break
                stripped = lines[i].strip()
                parts = stripped.split()
                if len(parts) >= 2:
                    if parts[0] == "device":
                        device_names = parts[1:]
                    elif device_names:
                        vals: list[float | None] = []
                        for v in parts[1:]:
                            try:
                                vals.append(float(v))
                            except ValueError:
                                vals.append(None)
                        col_values[parts[0]] = vals
                i += 1
            for col_idx, dev_name in enumerate(device_names):
                dev_params: dict[str, float] = {}
                for param_name, vals in col_values.items():
                    if col_idx < len(vals) and vals[col_idx] is not None:
                        dev_params[param_name] = vals[col_idx]  # type: ignore[assignment]
                if dev_params:
                    result[dev_name] = dev_params
        else:
            i += 1
    return result


_SIM_ERROR_PATTERNS: list[tuple[str, int]] = [
    (r"\bsingular matrix\b", re.IGNORECASE),
    (r"\bno convergence\b", re.IGNORECASE),
    (r"\biteration limit reached\b", re.IGNORECASE),
    (r"\btimestep too small\b", re.IGNORECASE),
]


def _check_simulation_errors(stdout: str, stderr: str) -> None:
    combined = stdout + "\n" + stderr
    for pattern, flags in _SIM_ERROR_PATTERNS:
        if re.search(pattern, combined, flags):
            snippet = combined[:500]
            raise SpiceSimulationError(
                f"ngspice simulation failed (matched pattern '{pattern}').\n"
                f"Output snippet:\n{snippet}"
            )


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def run_spice(
    netlist: str,
    analysis: str = "op",
    timeout_sec: float = 30.0,
) -> SpiceResult:
    """Run ngspice in batch mode and return parsed results.

    Args:
        netlist: Complete SPICE netlist string (must end with .end).
        analysis: Analysis type. Phase 1 supports "op" only.
        timeout_sec: Subprocess timeout in seconds.

    Returns:
        SpiceResult with parsed node voltages, branch currents, and device parameters.

    Raises:
        ValueError: If analysis type is not supported.
        SpiceExecutionError: If ngspice cannot be executed (not in PATH, timeout,
            non-zero exit code).
        SpiceSimulationError: If ngspice runs but simulation fails (singular matrix,
            no convergence, iteration limit reached, timestep too small).
    """
    if analysis != "op":
        raise ValueError(f"Phase 1 only supports 'op' analysis, got '{analysis}'")

    netlist_with_analysis = _inject_analysis(netlist, analysis)

    with tempfile.TemporaryDirectory() as tmpdir:
        cir_path = Path(tmpdir) / "circuit.cir"
        cir_path.write_text(netlist_with_analysis, encoding="utf-8")

        try:
            proc = subprocess.run(
                ["ngspice", "-b", str(cir_path)],
                capture_output=True,
                text=True,
                timeout=timeout_sec,
            )
        except FileNotFoundError as exc:
            raise SpiceExecutionError(
                f"ngspice not found in PATH: {exc}"
            ) from exc
        except subprocess.TimeoutExpired as exc:
            raise SpiceExecutionError(
                f"ngspice timed out after {timeout_sec}s"
            ) from exc

        stdout = proc.stdout
        stderr = proc.stderr

        if proc.returncode != 0:
            raise SpiceExecutionError(
                f"ngspice exited with code {proc.returncode}.\n"
                f"stderr: {stderr[:500]}\nstdout: {stdout[:500]}"
            )

        _check_simulation_errors(stdout, stderr)

        return SpiceResult(
            analysis=analysis,
            node_voltages=_parse_node_voltages(stdout),
            branch_currents=_parse_branch_currents(stdout),
            device_parameters=_parse_device_parameters(stdout),
            raw_stdout=stdout,
            raw_stderr=stderr,
        )
