from __future__ import annotations

import re

from src.topology.models import Circuit

_PREFIX_FOR_KIND: dict[str, str] = {
    "nmos": "M",
    "pmos": "M",
    "resistor": "R",
    "capacitor": "C",
    "current_source": "I",
}

DEFAULT_MODEL_PARAMS: dict[str, dict[str, float]] = {
    "nmos": {"Vth": 0.5, "mun_Cox": 100e-6, "lambda": 0.0},
    "pmos": {"Vth": 0.5, "mup_Cox": 100e-6, "lambda": 0.0},
}


def _spice_node(circuit: Circuit, terminal: str) -> str:
    """Return the SPICE node name for a terminal. Ground nodes map to '0'."""
    node_id = circuit.incidence.node_of_terminal(terminal)
    return "0" if circuit.nodes[node_id].role == "ground" else node_id


def _model_name_for(dev_id: str, kind: str, model_params: dict) -> str:
    """Return the .MODEL name for a MOSFET device.

    If model_params contains a per-device entry keyed by dev_id, return a
    device-specific name; otherwise return the shared NMOS_L1 / PMOS_L1 name.
    """
    if dev_id in model_params:
        safe = dev_id.replace("-", "_")
        return f"NMOS_{safe}" if kind == "nmos" else f"PMOS_{safe}"
    return "NMOS_L1" if kind == "nmos" else "PMOS_L1"


def circuit_to_netlist(
    circuit: Circuit,
    model_params: dict[str, dict[str, float]] | None = None,
) -> str:
    """Generate an ngspice-dialect SPICE netlist string from a Circuit.

    model_params format:
      Shared model (Level 1 / single-stage):
        {"nmos": {"Vth": ..., "mun_Cox": ..., "lambda": ...}, "pmos": {...}}

      Per-device model (multi-stage, ADR-008 D3):
        {"nmos": {...}, "pmos": {...},
         "M1": {"Vth": ..., "mun_Cox": ..., "lambda": ...},
         "M1_sig_s2": {"Vth": ..., "mun_Cox": ..., "lambda": ...}, ...}

      When a device ID key is present, that MOSFET gets its own .MODEL line.
    """
    params = DEFAULT_MODEL_PARAMS if model_params is None else model_params

    # --- parameter contracts ---
    if params["nmos"]["mun_Cox"] <= 0:
        raise ValueError(
            f"model_params['nmos']['mun_Cox'] must be positive "
            f"(got {params['nmos']['mun_Cox']})"
        )
    if params["pmos"]["mup_Cox"] <= 0:
        raise ValueError(
            f"model_params['pmos']['mup_Cox'] must be positive "
            f"(got {params['pmos']['mup_Cox']})"
        )
    for kind in ("nmos", "pmos"):
        if params[kind]["Vth"] <= 0:
            raise ValueError(
                f"model_params['{kind}']['Vth'] must be positive "
                f"(got {params[kind]['Vth']}); writer applies sign based on device kind"
            )

    # --- device id prefix contract ---
    for dev_id, dev in sorted(circuit.devices.items()):
        expected = _PREFIX_FOR_KIND[dev.kind]
        if not dev_id.startswith(expected):
            raise ValueError(
                f"Device id '{dev_id}' must start with '{expected}' for kind='{dev.kind}'"
            )

    lines: list[str] = []

    # --- header ---
    lines.append(f"* Generated from Circuit sample_id={circuit.sample_id}")
    lines.append(f"* Devices: {len(circuit.devices)}, Nodes: {len(circuit.nodes)}")
    for node_id, node in sorted(circuit.nodes.items()):
        if node.role == "input" and node.voltage_dc is None:
            lines.append(f"* INPUT: {node_id} (DC not set)")
    lines.append("")

    # --- voltage sources: supply nodes ---
    for node_id, node in sorted(circuit.nodes.items()):
        if node.role == "supply":
            if node.voltage_dc is None:
                raise ValueError(
                    f"Supply node '{node_id}' has voltage_dc=None; "
                    "set it before generating netlist"
                )
            lines.append(f"V_{node_id} {node_id} 0 DC {node.voltage_dc:.6g}")

    # --- voltage sources: input nodes with DC set ---
    for node_id, node in sorted(circuit.nodes.items()):
        if node.role == "input" and node.voltage_dc is not None:
            lines.append(f"V_{node_id} {node_id} 0 DC {node.voltage_dc:.6g}")

    # --- device lines ---
    for dev_id, dev in sorted(circuit.devices.items()):
        if dev.kind in ("nmos", "pmos"):
            mname = _model_name_for(dev_id, dev.kind, params)
            d = _spice_node(circuit, f"{dev_id}.D")
            g = _spice_node(circuit, f"{dev_id}.G")
            s = _spice_node(circuit, f"{dev_id}.S")
            b = _spice_node(circuit, f"{dev_id}.B")
            W = dev.metadata.get("W")
            L = dev.metadata.get("L")
            if W is None or L is None:
                raise ValueError(f"MOSFET '{dev_id}' metadata missing 'W' or 'L'")
            lines.append(f"{dev_id} {d} {g} {s} {b} {mname} W={W:.6g} L={L:.6g}")
        elif dev.kind == "resistor":
            a = _spice_node(circuit, f"{dev_id}.a")
            b = _spice_node(circuit, f"{dev_id}.b")
            value = dev.metadata.get("value")
            if value is None:
                raise ValueError(f"Resistor '{dev_id}' metadata missing 'value'")
            lines.append(f"{dev_id} {a} {b} {value:.6g}")
        elif dev.kind == "capacitor":
            a = _spice_node(circuit, f"{dev_id}.a")
            b = _spice_node(circuit, f"{dev_id}.b")
            value = dev.metadata.get("value")
            if value is None:
                raise ValueError(f"Capacitor '{dev_id}' metadata missing 'value'")
            lines.append(f"{dev_id} {a} {b} {value:.6g}")
        elif dev.kind == "current_source":
            a = _spice_node(circuit, f"{dev_id}.a")  # n+
            b = _spice_node(circuit, f"{dev_id}.b")  # n-
            value = dev.metadata.get("value")
            if value is None:
                raise ValueError(f"Current source '{dev_id}' metadata missing 'value'")
            lines.append(f"{dev_id} {a} {b} DC {value:.6g}")

    # --- model definitions ---
    lines.append("")
    n = params["nmos"]
    p = params["pmos"]

    # Collect MOSFETs with per-device models
    per_device_emitted: set[str] = set()
    for dev_id, dev in sorted(circuit.devices.items()):
        if dev.kind in ("nmos", "pmos") and dev_id in params:
            dp = params[dev_id]
            mname = _model_name_for(dev_id, dev.kind, params)
            if mname not in per_device_emitted:
                if dev.kind == "nmos":
                    lines.append(
                        f".MODEL {mname} NMOS "
                        f"(LEVEL=1 VTO={dp['Vth']:.6g} KP={dp['mun_Cox']:.6g} LAMBDA={dp['lambda']:.6g})"
                    )
                else:
                    lines.append(
                        f".MODEL {mname} PMOS "
                        f"(LEVEL=1 VTO=-{dp['Vth']:.6g} KP={dp['mup_Cox']:.6g} LAMBDA={dp['lambda']:.6g})"
                    )
                per_device_emitted.add(mname)

    # Shared fallback models (always emitted; used by devices without per-device entry)
    lines.append(
        f".MODEL NMOS_L1 NMOS "
        f"(LEVEL=1 VTO={n['Vth']:.6g} KP={n['mun_Cox']:.6g} LAMBDA={n['lambda']:.6g})"
    )
    lines.append(
        f".MODEL PMOS_L1 PMOS "
        f"(LEVEL=1 VTO=-{p['Vth']:.6g} KP={p['mup_Cox']:.6g} LAMBDA={p['lambda']:.6g})"
    )
    lines.append("")
    lines.append(".end")

    return "\n".join(lines)
