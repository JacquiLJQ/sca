from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml

from src.topology.models import Circuit, Device, IncidenceMatrix, Node
from src.utils.netlist_writer import DEFAULT_MODEL_PARAMS


def build_model_params(given: dict[str, Any]) -> dict[str, dict[str, float]]:
    """Build model_params dict for circuit_to_netlist from a golden 'given' block.

    NMOS params come from 'given'; PMOS defaults come from DEFAULT_MODEL_PARAMS
    (Phase 1 circuits are all-NMOS, so PMOS values are never exercised here).
    """
    pmos_base = DEFAULT_MODEL_PARAMS["pmos"]
    return {
        "nmos": {
            "Vth": float(given["Vth"]),
            "mun_Cox": float(given["mun_Cox"]),
            "lambda": float(given.get("lambda", 0.0)),
        },
        "pmos": {
            "Vth": float(given.get("pmos_Vth", pmos_base["Vth"])),
            "mup_Cox": float(given.get("pmos_mup_Cox", pmos_base["mup_Cox"])),
            "lambda": float(given.get("pmos_lambda", pmos_base["lambda"])),
        },
    }


def circuit_from_cs_resistor_given(given: dict[str, Any]) -> Circuit:
    """Build a CS-with-resistor-load Circuit from a golden 'given' block.

    Hardcodes the CS+resistor topology (M1 NMOS + RD). Phase 1 only.
    When additional topologies are added, refactor into a topology-keyed
    dispatch so this function is no longer responsible for topology selection.
    """
    W = float(given["W"])
    L = float(given["L"])
    RD = float(given["RD"])
    VDD = float(given["VDD"])
    VG_DC = float(given["VG_DC"])

    incidence = IncidenceMatrix(
        nodes=["VDD", "vo", "vin", "GND"],
        terminals=["M1.D", "M1.G", "M1.S", "M1.B", "RD.a", "RD.b"],
        matrix=[
            [0, 0, 0, 0, 1, 0],  # VDD  — RD.a
            [1, 0, 0, 0, 0, 1],  # vo   — M1.D, RD.b
            [0, 1, 0, 0, 0, 0],  # vin  — M1.G
            [0, 0, 1, 1, 0, 0],  # GND  — M1.S, M1.B
        ],
    )
    devices = {
        "M1": Device(
            id="M1",
            kind="nmos",
            terminals=["D", "G", "S", "B"],
            metadata={"W": W, "L": L},
        ),
        "RD": Device(
            id="RD",
            kind="resistor",
            terminals=["a", "b"],
            metadata={"value": RD},
        ),
    }
    nodes = {
        "VDD": Node(id="VDD", role="supply", voltage_dc=VDD),
        "GND": Node(id="GND", role="ground", voltage_dc=0.0),
        "vo":  Node(id="vo",  role="output", voltage_dc=None),
        "vin": Node(id="vin", role="input",  voltage_dc=VG_DC),
    }
    return Circuit(
        sample_id="golden_cs_resistor_load",
        incidence=incidence,
        devices=devices,
        nodes=nodes,
    )


def load_golden(path: Path) -> dict[str, Any]:
    """Load and return a golden YAML file as a plain dict."""
    with path.open() as f:
        return yaml.safe_load(f)
