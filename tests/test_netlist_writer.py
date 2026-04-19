import pytest

from src.topology.models import Circuit, Device, IncidenceMatrix, Node
from src.utils.netlist_writer import circuit_to_netlist


@pytest.mark.unit
def test_netlist_contains_mosfet_line(cs_resistor_circuit_with_dc: Circuit) -> None:
    expected = "M1 vo vin 0 0 NMOS_L1 W=1e-06 L=1e-07"
    netlist = circuit_to_netlist(cs_resistor_circuit_with_dc)
    assert any(line.strip() == expected for line in netlist.splitlines())


@pytest.mark.unit
def test_netlist_contains_resistor_line(cs_resistor_circuit_with_dc: Circuit) -> None:
    expected = "RD VDD vo 10000"
    netlist = circuit_to_netlist(cs_resistor_circuit_with_dc)
    assert any(line.strip() == expected for line in netlist.splitlines())


@pytest.mark.unit
def test_netlist_contains_supply_source(cs_resistor_circuit_with_dc: Circuit) -> None:
    expected = "V_VDD VDD 0 DC 1.8"
    netlist = circuit_to_netlist(cs_resistor_circuit_with_dc)
    assert any(line.strip() == expected for line in netlist.splitlines())


@pytest.mark.unit
def test_netlist_contains_input_source(cs_resistor_circuit_with_dc: Circuit) -> None:
    expected = "V_vin vin 0 DC 0.9"
    netlist = circuit_to_netlist(cs_resistor_circuit_with_dc)
    assert any(line.strip() == expected for line in netlist.splitlines())


@pytest.mark.unit
def test_netlist_ends_with_dot_end(cs_resistor_circuit_with_dc: Circuit) -> None:
    netlist = circuit_to_netlist(cs_resistor_circuit_with_dc)
    non_empty = [line for line in netlist.splitlines() if line.strip()]
    assert non_empty[-1].strip() == ".end"


@pytest.mark.unit
def test_netlist_raises_on_missing_supply_voltage(cs_resistor_circuit: Circuit) -> None:
    bad_nodes = dict(cs_resistor_circuit.nodes)
    bad_nodes["VDD"] = Node(id="VDD", role="supply", voltage_dc=None)
    bad_circuit = cs_resistor_circuit.model_copy(update={"nodes": bad_nodes})
    with pytest.raises(ValueError, match="VDD"):
        circuit_to_netlist(bad_circuit)


@pytest.mark.unit
def test_netlist_raises_on_id_prefix_mismatch() -> None:
    bad_dev = Device(
        id="transistor1",
        kind="nmos",
        terminals=["D", "G", "S", "B"],
        metadata={"W": 1e-6, "L": 1e-7},
    )
    circuit = Circuit(
        sample_id="bad-prefix-test",
        incidence=IncidenceMatrix(
            nodes=["VDD", "GND"],
            terminals=["transistor1.D", "transistor1.G", "transistor1.S", "transistor1.B"],
            matrix=[[1, 0, 0, 0], [0, 1, 1, 1]],
        ),
        devices={"transistor1": bad_dev},
        nodes={
            "VDD": Node(id="VDD", role="supply", voltage_dc=1.8),
            "GND": Node(id="GND", role="ground", voltage_dc=0.0),
        },
    )
    with pytest.raises(ValueError) as exc_info:
        circuit_to_netlist(circuit)
    assert "transistor1" in str(exc_info.value)
    assert "'M'" in str(exc_info.value)


@pytest.mark.unit
def test_netlist_includes_model_definitions(cs_resistor_circuit_with_dc: Circuit) -> None:
    netlist = circuit_to_netlist(cs_resistor_circuit_with_dc)
    assert ".MODEL NMOS_L1" in netlist
    assert ".MODEL PMOS_L1" in netlist


@pytest.mark.unit
def test_netlist_header_comment(cs_resistor_circuit_with_dc: Circuit) -> None:
    first_line = circuit_to_netlist(cs_resistor_circuit_with_dc).splitlines()[0]
    assert first_line == "* Generated from Circuit sample_id=test-cs-001"


@pytest.mark.unit
def test_netlist_raises_on_negative_vth(cs_resistor_circuit_with_dc: Circuit) -> None:
    bad_params = {
        "nmos": {"Vth": -0.5, "mun_Cox": 100e-6, "lambda": 0.0},
        "pmos": {"Vth": 0.5, "mup_Cox": 100e-6, "lambda": 0.0},
    }
    with pytest.raises(ValueError, match="Vth"):
        circuit_to_netlist(cs_resistor_circuit_with_dc, model_params=bad_params)


@pytest.mark.unit
def test_netlist_raises_on_negative_mun_cox(cs_resistor_circuit_with_dc: Circuit) -> None:
    bad_params = {
        "nmos": {"Vth": 0.5, "mun_Cox": -100e-6, "lambda": 0.0},
        "pmos": {"Vth": 0.5, "mup_Cox": 100e-6, "lambda": 0.0},
    }
    with pytest.raises(ValueError, match="mun_Cox"):
        circuit_to_netlist(cs_resistor_circuit_with_dc, model_params=bad_params)
