"""Phase 1 circuit generator: NMOS CS + resistor load.

Topology is fixed (same incidence matrix for all Phase 1 circuits).
Only electrical parameters are randomised. VG_DC is derived analytically
to guarantee MOSFET saturation — it is never sampled blindly.
"""

import math
import random
import uuid

from src.topology.models import Circuit, Device, IncidenceMatrix, Node

_FIXED_L: float = 1e-7   # 100 nm gate length, fixed for Phase 1
_MAX_ATTEMPTS: int = 20


def _build_cs_resistor_incidence() -> IncidenceMatrix:
    return IncidenceMatrix(
        nodes=["VDD", "vo", "vin", "GND"],
        terminals=["M1.D", "M1.G", "M1.S", "M1.B", "RD.a", "RD.b"],
        matrix=[
            [0, 0, 0, 0, 1, 0],  # VDD — RD.a
            [1, 0, 0, 0, 0, 1],  # vo  — M1.D, RD.b
            [0, 1, 0, 0, 0, 0],  # vin — M1.G
            [0, 0, 1, 1, 0, 0],  # GND — M1.S, M1.B
        ],
    )


def generate_cs_resistor_circuit(
    seed: int | None = None,
) -> tuple[Circuit, dict[str, float]]:
    """Randomly generate an NMOS CS + resistor load circuit.

    Returns:
        circuit: Circuit object (incidence matrix + devices + nodes).
        given:   Parameter dict for execute_reasoning_dag.
                 Required DAG keys: VDD, VG_DC, Vth, kn, lambda, CL, Cgd, RD.
                 Extra keys (mun_Cox, W, L) included for SPICE netlist generation.

                 To run SPICE: use build_model_params(given) from
                 tests.golden_helpers to construct the model_params argument
                 for circuit_to_netlist().

    seed: pass a fixed int for reproducible generation.

    Raises:
        ValueError: if no feasible parameter set is found within
                    _MAX_ATTEMPTS retries.
    """
    rng = random.Random(seed)

    for _attempt in range(_MAX_ATTEMPTS):
        VDD      = rng.uniform(1.2, 3.3)
        mun_Cox  = rng.uniform(50e-6, 500e-6)
        WL_ratio = rng.uniform(2.0, 50.0)
        Vth      = rng.uniform(0.3, 0.7)
        RD       = rng.uniform(500.0, 50_000.0)
        lam      = 0.0 if rng.random() < 0.5 else rng.uniform(0.01, 0.05)
        CL       = rng.uniform(10e-15, 500e-15)
        Cgd      = rng.uniform(1e-15, 20e-15)

        kn = mun_Cox * WL_ratio

        # Derive the maximum safe overdrive x = VGS - Vth that keeps M1 in
        # saturation (VDS ≥ VOV).
        #
        # Saturation condition with grounded source:
        #   VD = VDD - 0.5*kn*RD*x²  ≥  x
        # ⟺ 0.5*kn*RD*x² + x - VDD  ≤  0
        #
        # Positive root of the quadratic (a = 0.5*kn*RD):
        #   x_max = (-1 + sqrt(1 + 4·a·VDD)) / (2·a)
        a = 0.5 * kn * RD
        x_max = (-1.0 + math.sqrt(1.0 + 4.0 * a * VDD)) / (2.0 * a)

        # Also enforce VG_DC ≤ VDD.
        x_ceiling = min(x_max, VDD - Vth)

        # Leave a 15% margin from the saturation boundary; require at least
        # 0.1 V overdrive so the device has meaningful gm.
        x_upper = x_ceiling * 0.85
        x_lower = 0.1

        if x_upper <= x_lower:
            continue  # parameter set infeasible; retry

        x = rng.uniform(x_lower, x_upper)
        VG_DC = Vth + x

        # Explicit feasibility guard (should always pass given the math above).
        VOV = VG_DC - Vth
        ID  = 0.5 * kn * VOV ** 2
        VD  = VDD - ID * RD
        if not (VD >= VOV and 0.0 < VD < VDD):
            continue

        # Build Circuit ---------------------------------------------------
        W = WL_ratio * _FIXED_L

        sample_id = (
            f"cs_resistor_{seed}"
            if seed is not None
            else f"cs_resistor_{uuid.uuid4().hex[:8]}"
        )

        circuit = Circuit(
            sample_id=sample_id,
            incidence=_build_cs_resistor_incidence(),
            devices={
                "M1": Device(
                    id="M1",
                    kind="nmos",
                    terminals=["D", "G", "S", "B"],
                    metadata={"W": W, "L": _FIXED_L},
                ),
                "RD": Device(
                    id="RD",
                    kind="resistor",
                    terminals=["a", "b"],
                    metadata={"value": RD},
                ),
            },
            nodes={
                "VDD": Node(id="VDD", role="supply", voltage_dc=VDD),
                "GND": Node(id="GND", role="ground", voltage_dc=0.0),
                "vo":  Node(id="vo",  role="output", voltage_dc=None),
                "vin": Node(id="vin", role="input",  voltage_dc=VG_DC),
            },
        )

        given: dict[str, float] = {
            # Required by CS_RESISTOR_TEMPLATE
            "VDD":    VDD,
            "VG_DC":  VG_DC,
            "Vth":    Vth,
            "kn":     kn,
            "lambda": lam,
            "CL":     CL,
            "Cgd":    Cgd,
            "RD":     RD,
            # Extras for circuit_to_netlist / SPICE (ignored by DAG executor)
            "mun_Cox": mun_Cox,
            "W":       W,
            "L":       _FIXED_L,
        }

        return circuit, given

    raise ValueError(
        f"generate_cs_resistor_circuit: no feasible parameters found after "
        f"{_MAX_ATTEMPTS} attempts. Consider relaxing parameter ranges."
    )
