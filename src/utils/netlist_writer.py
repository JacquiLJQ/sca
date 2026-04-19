from __future__ import annotations

from src.topology.models import Circuit

_PREFIX_FOR_KIND: dict[str, str] = {
    "nmos": "M",
    "pmos": "M",
    "resistor": "R",
    "capacitor": "C",
}

DEFAULT_MODEL_PARAMS: dict[str, dict[str, float]] = {
    "nmos": {"Vth": 0.5, "kn": 1e-3, "lambda": 0.0},
    "pmos": {"Vth": 0.5, "kn": 1e-3, "lambda": 0.0},
}


def _spice_node(circuit: Circuit, terminal: str) -> str:
    """Return the SPICE node name for a terminal. Ground nodes map to '0'."""
    node_id = circuit.incidence.node_of_terminal(terminal)
    return "0" if circuit.nodes[node_id].role == "ground" else node_id


def circuit_to_netlist(
    circuit: Circuit,
    model_params: dict[str, dict[str, float]] | None = None,
) -> str:
    """Generate an ngspice-dialect SPICE netlist string from a Circuit.

    Returns a string; does not write to disk. Caller adds analysis
    commands (.op, .ac, etc.) before the returned .end line.

    Model parameter convention: Vth must be a positive magnitude.
    The writer emits VTO=+Vth for NMOS and VTO=-Vth for PMOS automatically.
    """
    params = DEFAULT_MODEL_PARAMS if model_params is None else model_params

    # Vth sign contract: must be positive; writer applies sign per kind
    for kind in ("nmos", "pmos"):
        if params[kind]["Vth"] <= 0:
            raise ValueError(
                f"model_params['{kind}']['Vth'] must be positive "
                f"(got {params[kind]['Vth']}); writer applies sign based on device kind"
            )

    # Device id prefix contract: writer's responsibility, not the model's
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
            model_name = "NMOS_L1" if dev.kind == "nmos" else "PMOS_L1"
            d = _spice_node(circuit, f"{dev_id}.D")
            g = _spice_node(circuit, f"{dev_id}.G")
            s = _spice_node(circuit, f"{dev_id}.S")
            b = _spice_node(circuit, f"{dev_id}.B")
            W = dev.metadata.get("W")
            L = dev.metadata.get("L")
            if W is None or L is None:
                raise ValueError(f"MOSFET '{dev_id}' metadata missing 'W' or 'L'")
            lines.append(f"{dev_id} {d} {g} {s} {b} {model_name} W={W:.6g} L={L:.6g}")
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

    # --- model definitions ---
    lines.append("")
    n = params["nmos"]
    p = params["pmos"]
    lines.append(
        f".MODEL NMOS_L1 NMOS "
        f"(LEVEL=1 VTO={n['Vth']:.6g} KP={n['kn']:.6g} LAMBDA={n['lambda']:.6g})"
    )
    lines.append(
        f".MODEL PMOS_L1 PMOS "
        f"(LEVEL=1 VTO=-{p['Vth']:.6g} KP={p['kn']:.6g} LAMBDA={p['lambda']:.6g})"
    )
    lines.append("")
    lines.append(".end")

    return "\n".join(lines)
