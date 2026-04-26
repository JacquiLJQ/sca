"""SPICE model parameter construction for Phase 1 circuits.

Moved from tests/golden_helpers.py so that production code in src/ can
import it without crossing the src/tests package boundary.
"""

from typing import Any

from src.utils.netlist_writer import DEFAULT_MODEL_PARAMS


def build_model_params(given: dict[str, Any]) -> dict[str, dict[str, float]]:
    """Build model_params dict for circuit_to_netlist from a given dict.

    NMOS params come from 'given'. PMOS params fall back to DEFAULT_MODEL_PARAMS
    (Phase 1 circuits are all-NMOS; PMOS values are never exercised here).

    Wraps all values in float() to handle PyYAML string-parsing of scientific
    notation (ADR-005).
    """
    pmos_base = DEFAULT_MODEL_PARAMS["pmos"]
    return {
        "nmos": {
            "Vth":     float(given["Vth"]),
            "mun_Cox": float(given["mun_Cox"]),
            "lambda":  float(given.get("lambda", 0.0)),
        },
        "pmos": {
            "Vth":     float(given.get("pmos_Vth",     pmos_base["Vth"])),
            "mup_Cox": float(given.get("pmos_mup_Cox", pmos_base["mup_Cox"])),
            "lambda":  float(given.get("pmos_lambda",  pmos_base["lambda"])),
        },
    }
