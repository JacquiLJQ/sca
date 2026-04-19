import pytest

from src.solver.spice_runner import (
    SpiceExecutionError,
    SpiceSimulationError,
    _inject_analysis,
    _parse_branch_currents,
    _parse_device_parameters,
    _parse_node_voltages,
    run_spice,
)
from src.topology.models import Circuit
from src.utils.netlist_writer import circuit_to_netlist

# ---------------------------------------------------------------------------
# Shared fake stdout fragments (8-space indent mirrors real ngspice format)
# ---------------------------------------------------------------------------

_NODE_VOLTAGE_STDOUT = (
    "        Node                                  Voltage\n"
    "        ----                                  -------\n"
    "        ----    -------\n"
    "        vo                               1.000000e+00\n"
    "        vin                              9.000000e-01\n"
    "        vdd                              1.800000e+00\n"
    "\n"
    "        Source        Current\n"
)

_BRANCH_CURRENT_STDOUT = (
    "        Source        Current\n"
    "        ------        -------\n"
    "\n"
    "        v_vdd#branch                     -8.00000e-05\n"
    "        v_vin#branch                     0.000000e+00\n"
    "\n"
    " Mos1 models\n"
)

_MOSFET_INSTANCE_STDOUT = (
    " Mos1: Level 1 MOSfet model with Meyer capacitance model\n"
    "     device                    m1\n"
    "      model               nmos_l1\n"
    "         id           8.00000e-05\n"
    "        vgs                   0.9\n"
    "        vds                   1.0\n"
    "         gm           4.00000e-04\n"
    "\n"
    " Resistor: Simple linear resistor\n"
)

_NO_MOSFET_STDOUT = (
    "        Node                                  Voltage\n"
    "        vo                               1.000000e+00\n"
    "\n"
    " Resistor: Simple linear resistor\n"
    "     device                    rd\n"
)


# ---------------------------------------------------------------------------
# Class 1: @pytest.mark.unit — parser unit tests (no ngspice)
# ---------------------------------------------------------------------------

@pytest.mark.unit
def test_parse_node_voltages_basic() -> None:
    result = _parse_node_voltages(_NODE_VOLTAGE_STDOUT)
    assert result == {"vo": 1.0, "vin": 0.9, "vdd": 1.8}


@pytest.mark.unit
def test_parse_node_voltages_empty_when_no_section() -> None:
    stdout = "No tables here\njust some random text\n"
    assert _parse_node_voltages(stdout) == {}


@pytest.mark.unit
def test_parse_branch_currents_basic() -> None:
    result = _parse_branch_currents(_BRANCH_CURRENT_STDOUT)
    assert result == {"v_vdd#branch": -8e-5, "v_vin#branch": 0.0}


@pytest.mark.unit
def test_parse_device_parameters_mos1() -> None:
    result = _parse_device_parameters(_MOSFET_INSTANCE_STDOUT)
    assert "m1" in result
    params = result["m1"]
    assert abs(params["id"] - 8e-5) < 1e-10
    assert abs(params["vgs"] - 0.9) < 1e-10
    assert abs(params["vds"] - 1.0) < 1e-10
    assert abs(params["gm"] - 4e-4) < 1e-10
    # "model" line must not appear (value "nmos_l1" is not a float)
    assert "model" not in params
    # Exactly the numeric fields must be captured
    assert set(params.keys()) == {"id", "vgs", "vds", "gm"}


@pytest.mark.unit
def test_parse_device_parameters_no_mosfet() -> None:
    assert _parse_device_parameters(_NO_MOSFET_STDOUT) == {}


@pytest.mark.unit
def test_inject_op_before_dot_end() -> None:
    netlist = "V1 vdd 0 DC 1.8\n.MODEL NMOS_L1 NMOS (LEVEL=1)\n\n.end"
    result = _inject_analysis(netlist, "op")
    lines = result.splitlines()
    dot_end_idx = lines.index(".end")
    assert dot_end_idx > 0
    assert lines[dot_end_idx - 1] == ".op"


@pytest.mark.unit
def test_inject_raises_when_no_dot_end() -> None:
    netlist = "V1 vdd 0 DC 1.8\n.MODEL NMOS_L1 NMOS (LEVEL=1)\n"
    with pytest.raises(ValueError, match=r"\.end"):
        _inject_analysis(netlist, "op")


# ---------------------------------------------------------------------------
# Class 2: @pytest.mark.spice — integration tests (real ngspice)
# ---------------------------------------------------------------------------

@pytest.mark.spice
def test_run_spice_op_cs_resistor(cs_resistor_circuit_with_dc: Circuit) -> None:
    netlist = circuit_to_netlist(cs_resistor_circuit_with_dc)
    result = run_spice(netlist, analysis="op")

    assert result.analysis == "op"
    assert len(result.raw_stdout) > 0

    # Node voltages within 5% of golden (ADR-003)
    assert abs(result.node_voltages["vo"] - 1.0) / 1.0 < 0.05
    assert abs(result.node_voltages["vin"] - 0.9) / 0.9 < 0.05
    assert abs(result.node_voltages["vdd"] - 1.8) / 1.8 < 0.05

    # Device parameters: ngspice uses lowercase "m1"
    assert "m1" in result.device_parameters
    m1 = result.device_parameters["m1"]
    assert abs(m1["id"] - 80e-6) / 80e-6 < 0.05
    assert abs(m1["gm"] - 4e-4) / 4e-4 < 0.05


@pytest.mark.spice
def test_run_spice_rejects_non_op_analysis(cs_resistor_circuit_with_dc: Circuit) -> None:
    netlist = circuit_to_netlist(cs_resistor_circuit_with_dc)
    with pytest.raises(ValueError, match="Phase 1"):
        run_spice(netlist, analysis="ac")


@pytest.mark.spice
def test_run_spice_raises_on_malformed_netlist() -> None:
    # Two voltage sources driving the same node to different voltages → singular matrix
    bad_netlist = (
        "* conflicting sources test\n"
        "V1 n1 0 DC 1.0\n"
        "V2 n1 0 DC 2.0\n"
        ".end\n"
    )
    with pytest.raises((SpiceExecutionError, SpiceSimulationError)):
        run_spice(bad_netlist, analysis="op")
