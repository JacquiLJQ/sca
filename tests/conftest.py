import pytest

from src.topology.models import Circuit, Device, IncidenceMatrix, Node


def _build_cs_resistor_incidence() -> IncidenceMatrix:
    return IncidenceMatrix(
        nodes=["VDD", "vo", "vin", "GND"],
        terminals=["M1.D", "M1.G", "M1.S", "M1.B", "RD.a", "RD.b"],
        matrix=[
            [0, 0, 0, 0, 1, 0],  # VDD  — RD.a
            [1, 0, 0, 0, 0, 1],  # vo   — M1.D, RD.b
            [0, 1, 0, 0, 0, 0],  # vin  — M1.G
            [0, 0, 1, 1, 0, 0],  # GND  — M1.S, M1.B
        ],
    )


def _build_cs_resistor_devices() -> dict[str, Device]:
    return {
        "M1": Device(
            id="M1",
            kind="nmos",
            terminals=["D", "G", "S", "B"],
            metadata={"W": 2e-6, "L": 180e-9, "model": "nmos_lvt"},
        ),
        "RD": Device(
            id="RD",
            kind="resistor",
            terminals=["a", "b"],
            metadata={"value": 10000.0},
        ),
    }


@pytest.fixture
def cs_resistor_circuit() -> Circuit:
    """NMOS CS + resistor load. vin.voltage_dc is None (DC not set)."""
    return Circuit(
        sample_id="test-cs-001",
        incidence=_build_cs_resistor_incidence(),
        devices=_build_cs_resistor_devices(),
        nodes={
            "VDD": Node(id="VDD", role="supply", voltage_dc=1.8),
            "GND": Node(id="GND", role="ground", voltage_dc=0.0),
            "vo": Node(id="vo", role="output", voltage_dc=None),
            "vin": Node(id="vin", role="input", voltage_dc=None),
        },
    )


@pytest.fixture
def cs_resistor_circuit_with_dc() -> Circuit:
    """NMOS CS + resistor load. All DC bias values set (VDD=1.8V, vin=0.9V)."""
    return Circuit(
        sample_id="test-cs-001",
        incidence=_build_cs_resistor_incidence(),
        devices=_build_cs_resistor_devices(),
        nodes={
            "VDD": Node(id="VDD", role="supply", voltage_dc=1.8),
            "GND": Node(id="GND", role="ground", voltage_dc=0.0),
            "vo": Node(id="vo", role="output", voltage_dc=None),
            "vin": Node(id="vin", role="input", voltage_dc=0.9),
        },
    )
