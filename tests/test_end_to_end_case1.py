from pathlib import Path

import pytest

from src.solver.spice_runner import run_spice
from src.utils.netlist_writer import circuit_to_netlist
from tests.golden_helpers import (
    build_model_params,
    circuit_from_cs_resistor_given,
    load_golden,
)

GOLDEN_YAML = Path(__file__).parent / "golden" / "golden_cs_resistor_load.yaml"


def _rel_error(actual: float, expected: float) -> float:
    return abs(actual - expected) / abs(expected)


@pytest.mark.spice
def test_case1_spice_matches_golden() -> None:
    golden = load_golden(GOLDEN_YAML)
    given = golden["given"]
    expected = golden["expected"]
    tol = golden["tolerance"]

    circuit = circuit_from_cs_resistor_given(given)
    model_params = build_model_params(given)

    netlist = circuit_to_netlist(circuit, model_params=model_params)
    result = run_spice(netlist, analysis="op")

    qp = expected["qpoint"]
    ss = expected["small_signal"]

    # Node voltages
    if qp["VD"] is not None:
        exp_vd = float(qp["VD"])
        assert _rel_error(result.node_voltages["vo"], exp_vd) < tol, (
            f"vo: got {result.node_voltages['vo']}, expected {exp_vd}"
        )
    if qp["VGS"] is not None:
        # VGS = VG - VS; VS=0 so VGS == vin node voltage
        exp_vgs = float(qp["VGS"])
        assert _rel_error(result.node_voltages["vin"], exp_vgs) < tol, (
            f"vin: got {result.node_voltages['vin']}, expected {exp_vgs}"
        )

    # Device parameters
    assert "m1" in result.device_parameters, "ngspice did not report m1 parameters"
    m1 = result.device_parameters["m1"]

    if qp["ID"] is not None:
        exp_id = float(qp["ID"])
        assert _rel_error(m1["id"], exp_id) < tol, (
            f"m1.id: got {m1['id']}, expected {exp_id}"
        )
    if qp["VDS"] is not None:
        exp_vds = float(qp["VDS"])
        assert _rel_error(m1["vds"], exp_vds) < tol, (
            f"m1.vds: got {m1['vds']}, expected {exp_vds}"
        )
    if ss["gm"] is not None:
        exp_gm = float(ss["gm"])
        assert _rel_error(m1["gm"], exp_gm) < tol, (
            f"m1.gm: got {m1['gm']}, expected {exp_gm}"
        )
