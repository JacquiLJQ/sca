import pytest
from pydantic import ValidationError

from src.topology.models import Circuit, Device, IncidenceMatrix, Node, Port

# cs_resistor_circuit fixture is provided by tests/conftest.py

# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

def test_port_validation_rejects_missing_partner() -> None:
    with pytest.raises(ValidationError) as exc_info:
        Port(
            name="in_n",
            type="signal_in",
            terminal="G",
            polarity="differential",
            impedance_level="high",
            dc_level="flexible",
            differential_partner=None,
        )
    assert "differential_partner" in str(exc_info.value)


def test_incidence_column_sum_valid(cs_resistor_circuit: Circuit) -> None:
    assert cs_resistor_circuit.incidence.validate_column_sum() is True


def test_incidence_column_sum_invalid() -> None:
    # Column 0 has two 1s — violates the single-1-per-column rule
    bad_matrix = [
        [1, 0],
        [1, 1],
    ]
    inc = IncidenceMatrix(nodes=["A", "B"], terminals=["X.a", "X.b"], matrix=bad_matrix)
    assert inc.validate_column_sum() is False


def test_circuit_check_consistency_catches_terminal_mismatch(cs_resistor_circuit: Circuit) -> None:
    # C1 declares terminals ["a","b"] → expects "C1.a" and "C1.b" in incidence, which aren't there
    c1 = Device(id="C1", kind="capacitor", terminals=["a", "b"], metadata={})
    bad_circuit = cs_resistor_circuit.model_copy(
        update={"devices": {**cs_resistor_circuit.devices, "C1": c1}}
    )
    with pytest.raises(ValueError, match="Terminal mismatch"):
        bad_circuit.check_consistency()


def test_device_rejects_wrong_terminals_for_mosfet() -> None:
    with pytest.raises(ValidationError, match="terminals"):
        Device(id="M1", kind="nmos", terminals=["foo", "bar"], metadata={})


def test_device_rejects_wrong_terminals_for_resistor() -> None:
    with pytest.raises(ValidationError, match="terminals"):
        Device(id="RD", kind="resistor", terminals=["a", "b", "c"], metadata={})


def test_incidence_column_sum_rejects_nonbinary() -> None:
    # Column 0 sums to 1 but contains a 2 and a -1 — not a valid binary matrix
    nonbinary_matrix = [
        [2, 0],
        [-1, 1],
    ]
    inc = IncidenceMatrix(nodes=["A", "B"], terminals=["X.a", "X.b"], matrix=nonbinary_matrix)
    assert inc.validate_column_sum() is False


def test_node_of_terminal_lookup(cs_resistor_circuit: Circuit) -> None:
    inc = cs_resistor_circuit.incidence
    assert inc.node_of_terminal("M1.D") == "vo"
    assert inc.node_of_terminal("M1.G") == "vin"
    assert inc.node_of_terminal("M1.S") == "GND"
    assert inc.node_of_terminal("RD.a") == "VDD"
    with pytest.raises(KeyError):
        inc.node_of_terminal("nonexistent.X")


def test_circuit_serialization_roundtrip(cs_resistor_circuit: Circuit) -> None:
    json_str = cs_resistor_circuit.model_dump_json()
    restored = Circuit.model_validate_json(json_str)

    assert restored.sample_id == cs_resistor_circuit.sample_id
    assert restored.incidence.nodes == cs_resistor_circuit.incidence.nodes
    assert restored.incidence.terminals == cs_resistor_circuit.incidence.terminals
    assert restored.incidence.matrix == cs_resistor_circuit.incidence.matrix
    assert set(restored.devices.keys()) == set(cs_resistor_circuit.devices.keys())
    assert set(restored.nodes.keys()) == set(cs_resistor_circuit.nodes.keys())
