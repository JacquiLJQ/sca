"""SPICE model parameter construction.

build_model_params(given, circuit=None) → model_params dict

When circuit is None (Level 1 / single-stage):  returns a shared-model dict
  {"nmos": {...}, "pmos": {...}}

When circuit is provided (Level 2 / multi-stage, ADR-008 D3): adds per-device
entries keyed by device ID so netlist_writer emits one .MODEL per MOSFET.
Stage index is inferred from device ID suffix "_sig_s{i}":
  M1           → stage 1   (reads kn_s1, Vth_s1, lambda_s1; falls back to bare kn etc.)
  M1_sig_s2    → stage 2   (reads kn_s2, Vth_s2, lambda_s2)
  M1_sig_s3    → stage 3   (reads kn_s3, Vth_s3, lambda_s3)
"""

from __future__ import annotations

import re
from typing import Any, TYPE_CHECKING

from src.utils.netlist_writer import DEFAULT_MODEL_PARAMS

if TYPE_CHECKING:
    from src.topology.models import Circuit


def _stage_index_from_device_id(dev_id: str) -> int | None:
    """Return stage index from '_sig_s{i}' suffix, or None for stage-1 devices."""
    m = re.search(r"_sig_s(\d+)$", dev_id)
    return int(m.group(1)) if m else None


def _nmos_params_for_stage(given: dict[str, Any], stage: int | None) -> dict[str, float]:
    """Extract nmos model params for a given stage index (None = stage 1 / bare keys)."""
    W = float(given.get("W", 10e-6))
    L = float(given.get("L", 1e-6))

    # Try stage-suffixed keys first, then bare keys
    def _get(key: str) -> float | None:
        if stage is not None:
            v = given.get(f"{key}_s{stage}")
            if v is not None:
                return float(v)
        # Bare key (also covers single-stage composed circuits that use sfx="")
        v = given.get(key)
        return float(v) if v is not None else None

    # kn → mun_Cox conversion
    kn = _get("kn")
    mun_cox_direct = _get("mun_Cox")
    if mun_cox_direct is not None:
        mun_cox = mun_cox_direct
    elif kn is not None:
        mun_cox = kn * L / W
    else:
        # Last fallback: use stage-1 kn for unrecognised stages
        kn_s1 = given.get("kn_s1", given.get("kn", 1e-3))
        mun_cox = float(kn_s1) * L / W

    Vth    = _get("Vth")    or 0.5
    lambda_ = _get("lambda") or 0.0

    return {"Vth": Vth, "mun_Cox": mun_cox, "lambda": lambda_}


def build_model_params(
    given: dict[str, Any],
    circuit: "Circuit | None" = None,
) -> dict[str, dict[str, float]]:
    """Build model_params dict for circuit_to_netlist.

    Without circuit: returns shared NMOS_L1 / PMOS_L1 models (Level 1 behaviour).
    With circuit: adds per-device NMOS model entries for each MOSFET (ADR-008 D3).
    """
    pmos_base = DEFAULT_MODEL_PARAMS["pmos"]
    pmos_params = {
        "Vth":     float(given.get("pmos_Vth",     pmos_base["Vth"])),
        "mup_Cox": float(given.get("pmos_mup_Cox", pmos_base["mup_Cox"])),
        "lambda":  float(given.get("pmos_lambda",  pmos_base["lambda"])),
    }

    # Shared NMOS fallback (used by single-stage circuits and as NMOS_L1 fallback)
    shared_nmos = _nmos_params_for_stage(given, stage=None)

    result: dict[str, Any] = {"nmos": shared_nmos, "pmos": pmos_params}

    if circuit is not None:
        # Per-device entries for every NMOS in the circuit (ADR-008 D3)
        for dev_id, dev in circuit.devices.items():
            if dev.kind == "nmos":
                stage = _stage_index_from_device_id(dev_id)
                # stage=None → device is stage 1 (no suffix, OR bare-key single stage)
                # For stage 1 in a multi-stage circuit the suffix is _s1, so try
                # explicit stage 1 first, then bare keys via _nmos_params_for_stage(None).
                if stage is None and any(f"kn_s1" in k for k in given):
                    stage = 1
                result[dev_id] = _nmos_params_for_stage(given, stage)

    return result
