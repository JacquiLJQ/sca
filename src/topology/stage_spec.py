"""Stage specification data structures for Level 2 composable stage architecture (ADR-007 D1-D3)."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Optional

from src.topology.models import IncidenceMatrix


@dataclass(frozen=True)
class PortSpec:
    """Named interface port on a StageSpec (ADR-007 D1)."""

    name: str
    kind: str           # "input", "output", "supply", "ground", "load_top", "load_bot"
    signal_type: str    # "voltage", "current"
    impedance: str      # "high", "medium", "low"
    role: str           # semantic: "gate", "drain", "source", "vdd", "gnd", "drain_load"
    node_ref: str       # local node name inside the stage (empty string for external-only ports)
    dc_from_given: Optional[str] = None   # if set, Node.voltage_dc = given[dc_from_given]
    dc_voltage_range: Optional[tuple[float, float]] = None  # acceptable DC voltage range


@dataclass(frozen=True)
class DeviceSpec:
    """One device inside a StageSpec."""

    local_id: str           # device id within stage, e.g. "M1", "RD"
    kind: str               # "nmos", "pmos", "resistor", "current_source"
    terminals: list[str]    # ["D","G","S","B"] or ["a","b"]
    param_keys: list[str]   # given dict keys for SPICE device params (W, L, value, …)


@dataclass(frozen=True)
class MicroDagEntry:
    """One step in a stage's internal DAG template.

    input_refs are strings that resolve to either:
      - keys in the given dict (e.g. "VG_DC", "kn", "RD")
      - output_local of an earlier MicroDagEntry (from this or a prior stage)
    The template_generator converts MicroDagEntry → DAGNode verbatim.
    """

    local_id: str           # descriptive node identifier (becomes DAGNode.id)
    step: int               # skill.md step number (3–8)
    rule_name: str          # function name in rules.py
    input_refs: list[str]   # ordered, matching the rule's parameter signature
    output_local: str       # output symbol (key written into resolved dict)


class CompatibilityLevel(Enum):
    """Three-level port compatibility result (ADR-007 D3)."""

    OK = "ok"
    WARN_LOADING = "warn_loading"
    INVALID = "invalid"


@dataclass
class StageSpec:
    """Complete specification for one composable building block (ADR-007 D1).

    The DAG template is split into sections that template_generator emits
    in skill.md step order:
        3: qpoint_entries → vds_entries
        4: satcheck_entries
        5: ss_entries
        6: rout_entries (load stages) + gain_entries (signal stages)
        7: hf_entries
        8: pole_entries
    """

    stage_type: str
    category: str                         # "signal" or "load"
    ports: dict[str, PortSpec]
    devices: list[DeviceSpec]
    local_nodes: list[str]                # internal node names before stage prefix
    local_incidence: IncidenceMatrix      # connectivity within the stage

    qpoint_entries: list[MicroDagEntry]   # step 3: Q-point (no VDS, no gm/ro)
    vds_entries: list[MicroDagEntry]      # step 3: VDS computation (topology-specific)
    satcheck_entries: list[MicroDagEntry] # step 4: saturation check(s)
    ss_entries: list[MicroDagEntry]       # step 5: gm, ro
    rout_entries: list[MicroDagEntry]     # step 6: load Rout contribution
    gain_entries: list[MicroDagEntry]     # step 6: Av, Av_dB, Rin (signal stages)
    hf_entries: list[MicroDagEntry]       # step 7: Cout
    pole_entries: list[MicroDagEntry]     # step 8: p1_omega, p1_Hz

    small_signal_summary_rule: str        # informational label


# ---------------------------------------------------------------------------
# Port compatibility check (ADR-007 D3)
# ---------------------------------------------------------------------------

_DRIVER_KINDS: frozenset[str] = frozenset({"output", "load_top"})
_RECEIVER_KINDS: frozenset[str] = frozenset({"input", "load_bot"})
_IMP_ORDER: dict[str, int] = {"low": 0, "medium": 1, "high": 2}


def are_ports_compatible(p_out: PortSpec, p_in: PortSpec) -> CompatibilityLevel:
    """Check whether p_out can drive p_in (ADR-007 D3).

    Returns OK, WARN_LOADING, or INVALID.
    """
    if p_out.kind not in _DRIVER_KINDS or p_in.kind not in _RECEIVER_KINDS:
        return CompatibilityLevel.INVALID

    if p_out.signal_type != p_in.signal_type:
        return CompatibilityLevel.INVALID

    # DC voltage range overlap
    if p_out.dc_voltage_range and p_in.dc_voltage_range:
        lo_o, hi_o = p_out.dc_voltage_range
        lo_i, hi_i = p_in.dc_voltage_range
        if hi_o < lo_i or hi_i < lo_o:
            return CompatibilityLevel.INVALID

    out_imp = _IMP_ORDER.get(p_out.impedance, 1)
    in_imp  = _IMP_ORDER.get(p_in.impedance, 1)
    if out_imp > in_imp:
        return CompatibilityLevel.WARN_LOADING
    return CompatibilityLevel.OK
