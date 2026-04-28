"""Random stage compositor: samples legal signal+load combinations (ADR-007 D7-D8).

Public API:
    compose_random_circuit(given, topo_key=None, seed=None, sample_id=None)
        → (Circuit, topo_key)

    generate_composed_circuit(seed=None, num_stages=1, sample_id=None)
        → ComposedCircuitResult

Single-stage selection uses the fixed _COMPOSITIONS table (backward-compatible).

Multi-stage selection is truly random: each stage independently samples from
SIGNAL_POOL × LOAD_POOL subject to hard constraints and DC-bias chaining.
Weights are read from config/composition_weights.yaml.
"""

from __future__ import annotations

import math
import random
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from src.solver.dag_executor import DAGNode
from src.solver.template_generator import generate_template
from src.topology.compositor import compose_stages
from src.topology.models import Circuit
from src.topology.stage_library import (
    CG_CORE,
    CS_CORE,
    CS_CORE_ICS,
    CURRENT_SOURCE_LOAD,
    RESISTOR_LOAD,
    SF_CORE,
)
from src.topology.stage_spec import StageSpec


# ---------------------------------------------------------------------------
# Single-stage composition table (backward-compatible)
# ---------------------------------------------------------------------------

_COMPOSITIONS: list[tuple[StageSpec, Optional[StageSpec], list[tuple[str, str]], str]] = [
    (CS_CORE,     RESISTOR_LOAD,       [("cs",  "vout", "load", "load_bot")], "cs_resistor"),
    (CS_CORE_ICS, CURRENT_SOURCE_LOAD, [("cs",  "vout", "load", "load_bot")], "cs_current_source"),
    (SF_CORE,     None,                [],                                      "sf_resistor"),
    (CG_CORE,     RESISTOR_LOAD,       [("cg",  "vout", "load", "load_bot")], "cg_resistor"),
]

_BY_KEY: dict[str, tuple[StageSpec, Optional[StageSpec], list[tuple[str, str]], str]] = {
    entry[3]: entry for entry in _COMPOSITIONS
}
_TOPO_KEYS: list[str] = [entry[3] for entry in _COMPOSITIONS]
_SPEC_BY_KEY: dict[str, tuple[StageSpec, Optional[StageSpec]]] = {
    k: (e[0], e[1]) for k, e in _BY_KEY.items()
}


# ---------------------------------------------------------------------------
# Multi-stage pool definitions (L2.6)
# ---------------------------------------------------------------------------

# Available signal types for random selection.
# TODO: Add cascode_core, diff_pair_core when multi-stage param generators are implemented.
_SIGNAL_POOL_KEYS: list[str] = ["cs_core", "sf_core", "cg_core"]

# Available load types for random selection.
# TODO: Add current_mirror_load, active_load when multi-stage support is added.
_LOAD_POOL_KEYS: list[str] = ["resistor_load", "current_source_load"]

# Load direction per signal type.
# "pullup"   → load sits between VDD and signal.vout  (CS, CG: drain load)
# "pulldown" → load sits between signal.vout and GND  (SF: source load)
# TODO Phase 3: migrate to PortSpec.load_polarity field
LOAD_DIRECTION: dict[str, str] = {
    "cs_core": "pullup",
    "cg_core": "pullup",
    "sf_core": "pulldown",
}

# Map (signal_type, load_type) → (actual signal_spec, actual load_spec).
# Notes:
#   "cs_core" + current_source_load → use CS_CORE_ICS (reverse Q-point solve).
#   "cg_core" + current_source_load → falls back to RESISTOR_LOAD (no VD rule for CG+ICS).
#   "sf_core" + any load           → standalone SF (Rs integrated in SF_CORE).
_COMBO_SPEC_MAP: dict[tuple[str, str], tuple[StageSpec, Optional[StageSpec]]] = {
    ("cs_core",  "resistor_load"):        (CS_CORE,     RESISTOR_LOAD),
    ("cs_core",  "current_source_load"):  (CS_CORE_ICS, CURRENT_SOURCE_LOAD),
    ("cg_core",  "resistor_load"):        (CG_CORE,     RESISTOR_LOAD),
    ("cg_core",  "current_source_load"):  (CG_CORE,     RESISTOR_LOAD),   # fallback: CG+ICS unsupported
    ("sf_core",  "resistor_load"):        (SF_CORE,     None),
    ("sf_core",  "current_source_load"):  (SF_CORE,     None),
}

# Human-readable topo_key for (signal_type, load_type) pairs.
_COMBO_TOPO_KEY: dict[tuple[str, str], str] = {
    ("cs_core",  "resistor_load"):        "cs_resistor",
    ("cs_core",  "current_source_load"):  "cs_current_source",
    ("cg_core",  "resistor_load"):        "cg_resistor",
    ("cg_core",  "current_source_load"):  "cg_resistor",
    ("sf_core",  "resistor_load"):        "sf_resistor",
    ("sf_core",  "current_source_load"):  "sf_resistor",
}


# ---------------------------------------------------------------------------
# Weight loading from config
# ---------------------------------------------------------------------------

def _load_composition_weights() -> tuple[dict[str, float], dict[str, float]]:
    """Load signal/load sampling weights from config/composition_weights.yaml.

    Falls back to built-in defaults if the file is absent or malformed.
    """
    _defaults = (
        {"cs_core": 5.0, "sf_core": 3.0, "cg_core": 2.0},
        {"resistor_load": 6.0, "current_source_load": 4.0},
    )
    config_path = Path(__file__).parent.parent.parent / "config" / "composition_weights.yaml"
    try:
        import yaml
        with open(config_path) as f:
            cfg = yaml.safe_load(f)
        sig_w = {k: float(v) for k, v in cfg.get("signal_weights", {}).items()}
        ld_w  = {k: float(v) for k, v in cfg.get("load_weights",  {}).items()}
        if sig_w and ld_w:
            return sig_w, ld_w
    except Exception:
        pass
    return _defaults


# ---------------------------------------------------------------------------
# Per-topology parameter generators
# Convention: return (params_dict, vout_dc) or raise ValueError if infeasible.
# vin_dc=None → stage 1 (free bias); vin_dc=float → stage 2+ (chained).
# ---------------------------------------------------------------------------

def _cs_r_params(
    rng: random.Random, vdd: float, sfx: str,
    vin_dc: Optional[float] = None, is_last: bool = True,
) -> tuple[dict[str, float], float]:
    """CS + RESISTOR_LOAD. Vout = VD = VDD − ID·RD."""
    Vth = 0.5
    if vin_dc is None:
        VOV = rng.uniform(0.3, 0.6)
    else:
        VOV = vin_dc - Vth
        if VOV < 0.15:
            raise ValueError(f"CS chained: vin_dc={vin_dc:.3f} → VOV={VOV:.3f} < 0.15")
    kn = rng.choice([0.5e-3, 1.0e-3, 2.0e-3])
    ID = 0.5 * kn * VOV**2
    target_VD = rng.uniform(0.35, 0.65) * vdd
    RD = (vdd - target_VD) / ID
    if not (500.0 <= RD <= 50_000.0):
        raise ValueError(f"CS: RD={RD:.0f} out of [500, 50000]")
    if target_VD <= VOV + 0.1:
        raise ValueError("CS: VDS headroom too small")
    lambda_ = rng.uniform(0.01, 0.05)
    vout_dc = vdd - ID * RD
    VG_DC = Vth + VOV if vin_dc is None else vin_dc
    return ({
        f"VG_DC{sfx}":  VG_DC,
        f"Vth{sfx}":    Vth,
        f"kn{sfx}":     kn,
        f"lambda{sfx}": lambda_,
        f"RD{sfx}":     RD,
    }, vout_dc)


def _cs_ics_params(
    rng: random.Random, vdd: float, sfx: str,
    vin_dc: Optional[float] = None, is_last: bool = True,
) -> tuple[dict[str, float], float]:
    """CS + CURRENT_SOURCE_LOAD (CS_CORE_ICS). Vout = VDS_target."""
    Vth = 0.5
    kn = rng.choice([0.5e-3, 1.0e-3, 2.0e-3])
    lambda_ = rng.uniform(0.01, 0.05)
    if vin_dc is None:
        # Stage 1: free — choose VOV from Iload, but derive Iload after VDS_target
        # to include CLM factor so MOSFET stays in saturation in SPICE.
        Iload_0 = rng.uniform(0.1e-3, 1.0e-3)
        VOV     = math.sqrt(2.0 * Iload_0 / kn)
    else:
        # Stage 2+: VG_DC = vin_dc → derive VOV
        VOV = vin_dc - Vth
        if VOV < 0.15:
            raise ValueError(f"CS_ICS chained: vin_dc={vin_dc:.3f} → VOV={VOV:.3f} < 0.15")
    VDS_target = rng.uniform(VOV + 0.3, min(vdd * 0.7, vdd - 0.5))
    if VDS_target <= VOV:
        raise ValueError("CS_ICS: VDS_target <= VOV")
    # Include CLM factor so the current source matches what the MOSFET carries
    # in saturation at VDS_target.  Without this, MOSFET goes into triode in SPICE.
    Iload = 0.5 * kn * VOV**2 * (1.0 + lambda_ * VDS_target)
    VG_DC = Vth + VOV   # pre-compute so the circuit node DC voltage is correct for SPICE
    return ({
        f"Iload{sfx}":       Iload,
        f"VDS_target{sfx}":  VDS_target,
        f"Vth{sfx}":         Vth,
        f"kn{sfx}":          kn,
        f"lambda{sfx}":      lambda_,
        f"VG_DC{sfx}":       VG_DC,
    }, VDS_target)   # Vout = VD = VDS (grounded source)


def _sf_params(
    rng: random.Random, sfx: str,
    vin_dc: Optional[float] = None, is_last: bool = True,
) -> tuple[dict[str, float], float]:
    """SF_CORE (standalone; source Rs integrated). Vout = VS = ID·Rs."""
    Vth = 0.5
    kn = rng.choice([0.5e-3, 1.0e-3, 2.0e-3])
    if vin_dc is None:
        # Stage 1 free: choose VOV and VS independently
        VOV = rng.uniform(0.2, 0.4)
        min_VS = 0.6 if not is_last else 0.3
        VS = rng.uniform(min_VS, 1.2)
        VG_DC = Vth + VOV + VS
    else:
        # Stage 2+: VG_DC = vin_dc, derive VS from VOV
        VG_DC  = vin_dc
        max_VOV = VG_DC - Vth - 0.1
        if max_VOV < 0.1:
            raise ValueError(f"SF chained: vin_dc={vin_dc:.3f} too low (max_VOV={max_VOV:.3f})")
        VOV = rng.uniform(0.1, min(max_VOV, 0.5))
        VS  = VG_DC - Vth - VOV          # VS = VGS − Vth − Vth = VG − VGS
        if not is_last and VS < 0.6:
            raise ValueError(f"SF chained non-last: VS={VS:.3f} < 0.6 (downstream stage would starve)")
    ID = 0.5 * kn * VOV**2
    if ID <= 0:
        raise ValueError("SF: ID <= 0")
    Rs_load = VS / ID
    lambda_  = rng.uniform(0.01, 0.05)
    return ({
        f"VG_DC{sfx}":     VG_DC,
        f"Vth{sfx}":       Vth,
        f"kn{sfx}":        kn,
        f"lambda{sfx}":    lambda_,
        f"Rs_load{sfx}":   Rs_load,
    }, VS)   # Vout = VS


def _cg_r_params(
    rng: random.Random, vdd: float, sfx: str,
    vin_dc: Optional[float] = None, is_last: bool = True,
) -> tuple[dict[str, float], float]:
    """CG + RESISTOR_LOAD. Vout = VD = VDD − ID·RD. Vin = source = Vin_DC."""
    Vth = 0.5
    VOV = rng.uniform(0.25, 0.5)
    kn  = rng.choice([0.5e-3, 1.0e-3, 2.0e-3])
    ID  = 0.5 * kn * VOV**2
    Vin_DC = vin_dc if vin_dc is not None else rng.uniform(0.1, 0.4)
    VG_bias = Vin_DC + Vth + VOV
    # Drain must clear source by at least VOV + margin (saturation)
    min_VD = Vin_DC + VOV + 0.15
    if min_VD >= vdd:
        raise ValueError(f"CG: Vin_DC={Vin_DC:.3f} leaves no headroom for VD")
    target_VD = rng.uniform(min_VD, min(0.8 * vdd, vdd - 0.3))
    RD = (vdd - target_VD) / ID
    if not (500.0 <= RD <= 50_000.0):
        raise ValueError(f"CG: RD={RD:.0f} out of [500, 50000]")
    vout_dc = vdd - ID * RD
    if (vout_dc - Vin_DC) < VOV + 0.05:
        raise ValueError("CG: VDS after compute is too small")
    lambda_ = rng.uniform(0.01, 0.05)
    return ({
        f"Vin_DC{sfx}":    Vin_DC,
        f"VG_bias{sfx}":   VG_bias,
        f"Vth{sfx}":       Vth,
        f"kn{sfx}":        kn,
        f"lambda{sfx}":    lambda_,
        f"RD{sfx}":        RD,
    }, vout_dc)


def _gen_stage_params(
    rng: random.Random,
    sig_key: str,
    load_key: str,
    vdd: float,
    sfx: str,
    vin_dc: Optional[float] = None,
    is_last: bool = True,
) -> tuple[dict[str, float], float]:
    """Dispatch to the correct per-topology param generator."""
    if sig_key == "cs_core":
        if load_key == "current_source_load":
            return _cs_ics_params(rng, vdd, sfx, vin_dc, is_last)
        return _cs_r_params(rng, vdd, sfx, vin_dc, is_last)
    if sig_key == "sf_core":
        return _sf_params(rng, sfx, vin_dc, is_last)
    if sig_key == "cg_core":
        # CG + ICS not supported → both load types use CG+R param generator
        return _cg_r_params(rng, vdd, sfx, vin_dc, is_last)
    raise ValueError(f"Unknown signal type: {sig_key!r}")


# ---------------------------------------------------------------------------
# Soft-constraint helper: rough Av estimate
# ---------------------------------------------------------------------------

def _estimate_av_magnitude(params: dict, plan: list[tuple[str, str]]) -> float:
    """First-order |Av_total| estimate without inter-stage loading."""
    av = 1.0
    n = len(plan)
    for i, (sig_key, load_key) in enumerate(plan, start=1):
        sfx = f"_s{i}" if n > 1 else ""
        kn  = params.get(f"kn{sfx}", 1e-3)
        Vth = params.get(f"Vth{sfx}", 0.5)
        if sig_key == "cs_core":
            if load_key == "current_source_load":
                Iload   = params.get(f"Iload{sfx}", 1e-4)
                lambda_ = params.get(f"lambda{sfx}", 0.1)
                VOV     = math.sqrt(2.0 * Iload / kn) if kn > 0 else 0.5
                ro      = 1.0 / (lambda_ * Iload) if lambda_ > 0 and Iload > 0 else 1e6
                av     *= kn * VOV * ro
            else:
                VG_DC = params.get(f"VG_DC{sfx}", Vth + 0.5)
                VOV   = VG_DC - Vth
                RD    = params.get(f"RD{sfx}", 1e4)
                av   *= kn * VOV * RD
        elif sig_key == "cg_core":
            Vin_DC  = params.get(f"Vin_DC{sfx}", 0.1)
            VG_bias = params.get(f"VG_bias{sfx}", Vin_DC + Vth + 0.4)
            VOV     = VG_bias - Vin_DC - Vth
            RD      = params.get(f"RD{sfx}", 1e4)
            av     *= kn * VOV * RD
        elif sig_key == "sf_core":
            Rs      = params.get(f"Rs_load{sfx}", 1e3)
            gm_est  = kn * 0.3       # typical VOV ≈ 0.3 V
            av     *= gm_est * Rs / (1.0 + gm_est * Rs)
    return abs(av)


# ---------------------------------------------------------------------------
# Stage-plan selection with hard constraints
# ---------------------------------------------------------------------------

def _select_stage_plan(
    rng: random.Random,
    n: int,
    sig_keys: list[str],
    sig_ws: list[float],
    load_keys: list[str],
    load_ws: list[float],
) -> list[tuple[str, str]]:
    """Select an n-stage plan respecting hard constraints.

    Hard constraints (ADR-007 D7):
    - Stage 1 must not be CG (low Rin unsuitable as first stage; use in TIA mode only).
    - No two consecutive SF stages (degenerate cascade with combined gain < 1).

    Raises ValueError after 100 inner tries if no valid plan is found.
    """
    for _ in range(100):
        plan: list[tuple[str, str]] = []
        ok = True
        for i in range(n):
            avail_sig = sig_keys[:]
            avail_ws  = sig_ws[:]
            # Constraint 1: stage 1 not CG
            if i == 0 and "cg_core" in avail_sig:
                j = avail_sig.index("cg_core")
                avail_sig.pop(j); avail_ws.pop(j)
            # Constraint 2: no consecutive SF
            if plan and plan[-1][0] == "sf_core" and "sf_core" in avail_sig:
                j = avail_sig.index("sf_core")
                avail_sig.pop(j); avail_ws.pop(j)
            if not avail_sig:
                ok = False; break
            sig  = rng.choices(avail_sig, weights=avail_ws)[0]
            load = rng.choices(load_keys, weights=load_ws)[0]
            plan.append((sig, load))
        if ok:
            return plan
    raise ValueError(f"Could not build a valid {n}-stage plan after 100 tries")


# ---------------------------------------------------------------------------
# ComposedCircuitResult
# ---------------------------------------------------------------------------

@dataclass
class ComposedCircuitResult:
    """Result of generate_composed_circuit."""
    circuit:    Circuit
    given:      dict[str, float]
    template:   list[DAGNode]
    stage_keys: list[str]   # topo_key per stage, e.g. ["cs_resistor", "sf_resistor"]


# ---------------------------------------------------------------------------
# Public: compose_random_circuit  (single-stage, backward-compatible)
# ---------------------------------------------------------------------------

def compose_random_circuit(
    given: dict[str, float],
    topo_key: Optional[str] = None,
    seed: Optional[int] = None,
    sample_id: Optional[str] = None,
) -> tuple[Circuit, str]:
    """Randomly select and compose a signal+load stage combination.

    Args:
        given:      Parameter dict (VDD, VG_DC, Vth, kn, RD, lambda, …)
        topo_key:   If set, use this specific composition key.
        seed:       RNG seed for reproducibility.
        sample_id:  Optional Circuit sample identifier.

    Returns: (Circuit, topo_key)
    Raises:  ValueError if topo_key is not in the composition table.
    """
    if topo_key is not None:
        if topo_key not in _BY_KEY:
            raise ValueError(f"Unknown topo_key {topo_key!r}. Valid: {_TOPO_KEYS}")
        entry = _BY_KEY[topo_key]
    else:
        entry = random.Random(seed).choice(_COMPOSITIONS)

    signal_spec, load_spec, raw_ics, key = entry

    if load_spec is None:
        circuit = compose_stages([("sf", signal_spec)], [], given, sample_id=sample_id)
    else:
        sig_id = raw_ics[0][0] if raw_ics else "stage"
        instances = [(sig_id, signal_spec), ("load", load_spec)]
        interconnections = [
            (f"{s}.{sp}", f"{l}.{lp}") for s, sp, l, lp in raw_ics
        ]
        circuit = compose_stages(instances, interconnections, given, sample_id=sample_id)

    return circuit, key


# ---------------------------------------------------------------------------
# Public: generate_composed_circuit  (multi-stage, truly random, L2.6)
# ---------------------------------------------------------------------------

def generate_composed_circuit(
    seed: Optional[int] = None,
    num_stages: int = 1,
    sample_id: Optional[str] = None,
) -> ComposedCircuitResult:
    """Generate a complete multi-stage composed circuit with feasible parameters.

    Each stage is randomly and independently drawn from SIGNAL_POOL × LOAD_POOL
    subject to hard constraints and DC-bias chaining (ADR-007 D7-D8).
    Stage-specific given-dict keys carry a _s{i} suffix (1-indexed).
    Shared keys (VDD, CL, Cgd, W, L) are un-suffixed.

    DC-bias chaining: stage i+1's input DC = stage i's output DC (DC-coupled).
    This guarantees physically consistent biasing across the cascade and reduces
    infeasibility. The physical Circuit object has no inter-stage signal
    connections (each stage is independently biased for SPICE purposes); the
    cascade relationship is represented entirely in the DAG template.

    Args:
        seed:       RNG seed for reproducibility.
        num_stages: 1, 2, or 3.
        sample_id:  Optional Circuit sample identifier.

    Returns: ComposedCircuitResult
    Raises:  ValueError for unsupported num_stages.
             RuntimeError if no feasible circuit is found after 20 outer attempts.
    """
    if num_stages not in (1, 2, 3):
        raise ValueError(f"num_stages must be 1, 2, or 3, got {num_stages}")

    rng = random.Random(seed)
    VDD = 5.0

    sig_w_dict, ld_w_dict = _load_composition_weights()
    sig_keys  = [k for k in _SIGNAL_POOL_KEYS if k in sig_w_dict]
    sig_ws    = [sig_w_dict[k] for k in sig_keys]
    load_keys = [k for k in _LOAD_POOL_KEYS  if k in ld_w_dict]
    load_ws   = [ld_w_dict[k] for k in load_keys]

    for _attempt in range(20):
        try:
            plan = _select_stage_plan(rng, num_stages, sig_keys, sig_ws, load_keys, load_ws)

            # Generate per-stage params chained via DC bias
            given: dict[str, float] = {
                "VDD": VDD, "CL": 1e-12, "Cgd": 0.1e-12, "W": 10e-6, "L": 1e-6,
            }
            vout_prev: Optional[float] = None
            stage_specs: list[tuple[StageSpec, Optional[StageSpec]]] = []

            for i, (sig_key, load_key) in enumerate(plan, start=1):
                # Single-stage: no suffix so the bare single-stage template resolves keys
                sfx     = f"_s{i}" if num_stages > 1 else ""
                is_last = (i == num_stages)
                stage_params, vout_dc = _gen_stage_params(
                    rng, sig_key, load_key, VDD, sfx,
                    vin_dc=vout_prev, is_last=is_last,
                )
                given.update(stage_params)
                vout_prev = vout_dc
                stage_specs.append(_COMBO_SPEC_MAP[(sig_key, load_key)])

            # Soft constraint: |Av_total| > 1 (rough first-order estimate)
            if _estimate_av_magnitude(given, plan) <= 1.0:
                continue

            # Build DAG template
            if num_stages == 1:
                sig, ld = stage_specs[0]
                template = generate_template(sig, ld)
            else:
                template = generate_template(stage_specs)

            # Build physical circuit with inter-stage signal connections (ADR-008 D1).
            # stage_i.vout → stage_{i+1}.vin is added for every adjacent pair so the
            # compositor merges them into one node (role="internal", no V_ source).
            instances:         list[tuple[str, StageSpec]] = []
            interconnections:  list[tuple[str, str]] = []
            stage_indices_list: list[int] = []

            for i, ((sig_key, _load_key), (sig_spec, ld_spec)) in enumerate(
                zip(plan, stage_specs), start=1
            ):
                sig_id  = f"sig_s{i}"
                load_id = f"load_s{i}"
                if ld_spec is None:
                    instances.append((sig_id, sig_spec))
                    stage_indices_list.append(i)
                else:
                    instances.append((sig_id, sig_spec))
                    instances.append((load_id, ld_spec))
                    interconnections.append((f"{sig_id}.vout", f"{load_id}.load_bot"))
                    stage_indices_list.extend([i, i])

                # Inter-stage signal connection: this stage's output → next stage's input
                if i < num_stages:
                    next_sig_id = f"sig_s{i + 1}"
                    interconnections.append((f"{sig_id}.vout", f"{next_sig_id}.vin"))

            circuit = compose_stages(
                instances, interconnections, given,
                sample_id=sample_id, stage_indices=stage_indices_list,
            )

            stage_keys = [_COMBO_TOPO_KEY[(sk, lk)] for sk, lk in plan]

            return ComposedCircuitResult(
                circuit=circuit, given=given, template=template, stage_keys=stage_keys,
            )

        except (ValueError, RuntimeError):
            continue

    raise RuntimeError(
        f"Failed to generate a feasible {num_stages}-stage circuit after 20 attempts"
    )
