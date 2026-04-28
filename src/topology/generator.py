"""Phase 2 circuit generators: CS+R, SF+R, CS+ICS, CG+R, Cascode+R.

All generators return (circuit, given) pairs where given is ready for
execute_reasoning_dag. A topology-agnostic dispatcher generate_random_circuit
returns (circuit, given, topo_key) for pipeline use.

VG_DC / bias voltages are derived analytically to guarantee MOSFET saturation;
they are never sampled blindly.
"""

import math
import random
import uuid

from src.topology.models import Circuit, Device, IncidenceMatrix, Node

_FIXED_L: float = 1e-7   # 100 nm gate length, fixed throughout Phase 2
_MAX_ATTEMPTS: int = 20

_TOPOLOGY_KEYS: list[str] = [
    "cs_resistor",
    "sf_resistor",
    "cs_current_source",
    "cg_resistor",
    "cascode_resistor",
]


# ---------------------------------------------------------------------------
# Shared analytical helper
# ---------------------------------------------------------------------------

def _max_overdrive(kn: float, R: float, VDD_eff: float) -> float:
    """Largest VOV keeping a single-transistor stage in saturation.

    Saturation boundary: VDD_eff - 0.5*kn*R*x² ≥ x
      → positive root of  0.5*kn*R*x² + x - VDD_eff = 0
      → x_max = (-1 + sqrt(1 + 4·(0.5·kn·R)·VDD_eff)) / (2·(0.5·kn·R))

    Works for CS+R, CG+R (with VDD_eff = VDD − Vin_DC), and SF+R
    (with R = Rs_load and VDD_eff = VDD).
    """
    a = 0.5 * kn * R
    return (-1.0 + math.sqrt(1.0 + 4.0 * a * VDD_eff)) / (2.0 * a)


# ---------------------------------------------------------------------------
# Incidence matrices
# ---------------------------------------------------------------------------

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


def _build_sf_resistor_incidence() -> IncidenceMatrix:
    return IncidenceMatrix(
        nodes=["VDD", "vo", "vin", "GND"],
        terminals=["M1.D", "M1.G", "M1.S", "M1.B", "Rs.a", "Rs.b"],
        matrix=[
            [1, 0, 0, 0, 0, 0],  # VDD — M1.D
            [0, 0, 1, 0, 1, 0],  # vo  — M1.S, Rs.a
            [0, 1, 0, 0, 0, 0],  # vin — M1.G
            [0, 0, 0, 1, 0, 1],  # GND — M1.B, Rs.b
        ],
    )


def _build_cs_ics_incidence() -> IncidenceMatrix:
    # I1.a = VDD (N+), I1.b = vo (N-): current flows VDD → vo, i.e. into drain
    return IncidenceMatrix(
        nodes=["VDD", "vo", "vin", "GND"],
        terminals=["M1.D", "M1.G", "M1.S", "M1.B", "I1.a", "I1.b"],
        matrix=[
            [0, 0, 0, 0, 1, 0],  # VDD — I1.a
            [1, 0, 0, 0, 0, 1],  # vo  — M1.D, I1.b
            [0, 1, 0, 0, 0, 0],  # vin — M1.G
            [0, 0, 1, 1, 0, 0],  # GND — M1.S, M1.B
        ],
    )


def _build_cg_resistor_incidence() -> IncidenceMatrix:
    return IncidenceMatrix(
        nodes=["VDD", "vo", "vin", "VG_bias", "GND"],
        terminals=["M1.D", "M1.G", "M1.S", "M1.B", "RD.a", "RD.b"],
        matrix=[
            [0, 0, 0, 0, 1, 0],  # VDD     — RD.a
            [1, 0, 0, 0, 0, 1],  # vo      — M1.D, RD.b
            [0, 0, 1, 0, 0, 0],  # vin     — M1.S (input at source)
            [0, 1, 0, 0, 0, 0],  # VG_bias — M1.G
            [0, 0, 0, 1, 0, 0],  # GND     — M1.B
        ],
    )


def _build_cascode_resistor_incidence() -> IncidenceMatrix:
    return IncidenceMatrix(
        nodes=["VDD", "vo", "vx", "vin", "VG2_bias", "GND"],
        terminals=[
            "M1.D", "M1.G", "M1.S", "M1.B",
            "M2.D", "M2.G", "M2.S", "M2.B",
            "RD.a", "RD.b",
        ],
        matrix=[
            [0, 0, 0, 0, 0, 0, 0, 0, 1, 0],  # VDD      — RD.a
            [0, 0, 0, 0, 1, 0, 0, 0, 0, 1],  # vo       — M2.D, RD.b
            [1, 0, 0, 0, 0, 0, 1, 0, 0, 0],  # vx       — M1.D, M2.S
            [0, 1, 0, 0, 0, 0, 0, 0, 0, 0],  # vin      — M1.G
            [0, 0, 0, 0, 0, 1, 0, 0, 0, 0],  # VG2_bias — M2.G
            [0, 0, 1, 1, 0, 0, 0, 1, 0, 0],  # GND      — M1.S, M1.B, M2.B
        ],
    )


# ---------------------------------------------------------------------------
# CS + resistor load (Phase 1, unchanged)
# ---------------------------------------------------------------------------

def generate_cs_resistor_circuit(
    seed: int | None = None,
) -> tuple[Circuit, dict[str, float]]:
    """Randomly generate an NMOS CS + resistor load circuit.

    Returns (circuit, given) where given is ready for CS_RESISTOR_TEMPLATE.
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
        W  = WL_ratio * _FIXED_L

        x_max     = _max_overdrive(kn, RD, VDD)
        x_ceiling = min(x_max, VDD - Vth)
        x_upper   = x_ceiling * 0.85
        x_lower   = 0.1

        if x_upper <= x_lower:
            continue

        x     = rng.uniform(x_lower, x_upper)
        VG_DC = Vth + x

        VOV = VG_DC - Vth
        ID  = 0.5 * kn * VOV ** 2
        VD  = VDD - ID * RD
        if not (VD >= VOV and 0.0 < VD < VDD):
            continue

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
                    id="M1", kind="nmos", terminals=["D", "G", "S", "B"],
                    metadata={"W": W, "L": _FIXED_L},
                ),
                "RD": Device(
                    id="RD", kind="resistor", terminals=["a", "b"],
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
            "VDD":    VDD,
            "VG_DC":  VG_DC,
            "Vth":    Vth,
            "kn":     kn,
            "lambda": lam,
            "CL":     CL,
            "Cgd":    Cgd,
            "RD":     RD,
            "mun_Cox": mun_Cox,
            "W":       W,
            "L":       _FIXED_L,
        }

        return circuit, given

    raise ValueError(
        f"generate_cs_resistor_circuit: no feasible parameters found after "
        f"{_MAX_ATTEMPTS} attempts."
    )


# ---------------------------------------------------------------------------
# SF + resistor source load
# ---------------------------------------------------------------------------

def generate_sf_resistor_circuit(
    seed: int | None = None,
) -> tuple[Circuit, dict[str, float]]:
    """Randomly generate an NMOS source follower + resistor source load.

    Returns (circuit, given) where given is ready for SF_RESISTOR_TEMPLATE.
    """
    rng = random.Random(seed)

    for _attempt in range(_MAX_ATTEMPTS):
        VDD      = rng.uniform(1.2, 3.3)
        mun_Cox  = rng.uniform(50e-6, 500e-6)
        WL_ratio = rng.uniform(2.0, 50.0)
        Vth      = rng.uniform(0.3, 0.7)
        Rs_load  = rng.uniform(500.0, 50_000.0)
        lam      = 0.0 if rng.random() < 0.3 else rng.uniform(0.01, 0.05)
        CL       = rng.uniform(10e-15, 500e-15)
        Cgd      = rng.uniform(1e-15, 20e-15)

        kn = mun_Cox * WL_ratio
        W  = WL_ratio * _FIXED_L

        # SF saturation: VDS = VDD - VS = VDD - 0.5·kn·Rs·VOV² ≥ VOV
        # Boundary is identical to CS formula with R = Rs_load.
        vov_max   = _max_overdrive(kn, Rs_load, VDD)
        x_upper   = min(vov_max * 0.85, VDD - Vth - 0.05)
        x_lower   = 0.1

        if x_upper <= x_lower:
            continue

        VOV = rng.uniform(x_lower, x_upper)
        ID  = 0.5 * kn * VOV ** 2
        VS  = ID * Rs_load
        VG_DC = Vth + VOV + VS   # VGS + VS = (Vth+VOV) + VS
        VDS = VDD - VS

        if not (VDS >= VOV and VS > 0.0 and VG_DC < VDD):
            continue

        sample_id = (
            f"sf_resistor_{seed}"
            if seed is not None
            else f"sf_resistor_{uuid.uuid4().hex[:8]}"
        )

        circuit = Circuit(
            sample_id=sample_id,
            incidence=_build_sf_resistor_incidence(),
            devices={
                "M1": Device(
                    id="M1", kind="nmos", terminals=["D", "G", "S", "B"],
                    metadata={"W": W, "L": _FIXED_L},
                ),
                "Rs": Device(
                    id="Rs", kind="resistor", terminals=["a", "b"],
                    metadata={"value": Rs_load},
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
            "VDD":     VDD,
            "VG_DC":   VG_DC,
            "Vth":     Vth,
            "kn":      kn,
            "lambda":  lam,
            "Rs_load": Rs_load,
            "CL":      CL,
            "Cgd":     Cgd,
            "mun_Cox": mun_Cox,
            "W":       W,
            "L":       _FIXED_L,
        }

        return circuit, given

    raise ValueError(
        f"generate_sf_resistor_circuit: no feasible parameters found after "
        f"{_MAX_ATTEMPTS} attempts."
    )


# ---------------------------------------------------------------------------
# CS + ideal current source load
# ---------------------------------------------------------------------------

def generate_cs_current_source_circuit(
    seed: int | None = None,
) -> tuple[Circuit, dict[str, float]]:
    """Randomly generate an NMOS CS + ideal current source load.

    lambda must be > 0 so ro is finite (Rout = ro is the circuit's output
    resistance). Returns (circuit, given) ready for CS_IDEAL_CURRENT_SOURCE_TEMPLATE.
    """
    rng = random.Random(seed)

    for _attempt in range(_MAX_ATTEMPTS):
        VDD      = rng.uniform(1.2, 3.3)
        mun_Cox  = rng.uniform(50e-6, 500e-6)
        WL_ratio = rng.uniform(2.0, 50.0)
        Vth      = rng.uniform(0.3, 0.7)
        lam      = rng.uniform(0.01, 0.05)   # must be > 0
        CL       = rng.uniform(10e-15, 500e-15)
        Cgd      = rng.uniform(1e-15, 20e-15)
        Cgs      = rng.uniform(1e-15, 20e-15)

        kn = mun_Cox * WL_ratio
        W  = WL_ratio * _FIXED_L

        # Sample VOV (lambda=0 approx) → derive Iload, then compute exact VOV with CLM.
        vov_max_approx = min(VDD - Vth - 0.1, 1.5)
        if vov_max_approx <= 0.1:
            continue

        VOV_approx = rng.uniform(0.1, vov_max_approx * 0.85)
        Iload      = 0.5 * kn * VOV_approx ** 2

        # VDS_target: sample with saturation margin over lambda=0 VOV
        VDS_lo = VOV_approx * 1.2
        VDS_hi = VDD * 0.7
        if VDS_hi <= VDS_lo:
            continue

        VDS_target = rng.uniform(VDS_lo, VDS_hi)

        # Exact VOV and VGS (including CLM), matching rule_vov_from_id_clm
        VOV_exact = math.sqrt(2.0 * Iload / (kn * (1.0 + lam * VDS_target)))
        VG_DC     = Vth + VOV_exact   # VS = 0

        if VG_DC >= VDD:
            continue

        sample_id = (
            f"cs_ics_{seed}"
            if seed is not None
            else f"cs_ics_{uuid.uuid4().hex[:8]}"
        )

        circuit = Circuit(
            sample_id=sample_id,
            incidence=_build_cs_ics_incidence(),
            devices={
                "M1": Device(
                    id="M1", kind="nmos", terminals=["D", "G", "S", "B"],
                    metadata={"W": W, "L": _FIXED_L},
                ),
                "I1": Device(
                    id="I1", kind="current_source", terminals=["a", "b"],
                    metadata={"value": Iload},
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
            "Iload":      Iload,
            "VDS_target": VDS_target,
            "Vth":        Vth,
            "kn":         kn,
            "lambda":     lam,
            "CL":         CL,
            "Cgd":        Cgd,
            "VDD":        VDD,
            "Cgs":        Cgs,
            "Rs":         0.0,
            "mun_Cox":    mun_Cox,
            "W":          W,
            "L":          _FIXED_L,
        }

        return circuit, given

    raise ValueError(
        f"generate_cs_current_source_circuit: no feasible parameters found after "
        f"{_MAX_ATTEMPTS} attempts."
    )


# ---------------------------------------------------------------------------
# CG + resistor drain load
# ---------------------------------------------------------------------------

def generate_cg_resistor_circuit(
    seed: int | None = None,
) -> tuple[Circuit, dict[str, float]]:
    """Randomly generate an NMOS CG + resistor drain load.

    Gate is held at a fixed bias VG_bias; signal enters at the source.
    Returns (circuit, given) ready for CG_RESISTOR_TEMPLATE.
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
        W  = WL_ratio * _FIXED_L

        # Source terminal DC level
        Vin_DC  = rng.uniform(0.1, VDD * 0.35)
        VDD_eff = VDD - Vin_DC   # effective headroom for drain swing

        # Saturation: VDS = VD − Vin_DC ≥ VOV; same formula as CS with VDD_eff.
        vov_max     = _max_overdrive(kn, RD, VDD_eff)
        # Also enforce VG_bias = Vin_DC + Vth + VOV < VDD
        vov_max_gate = VDD - Vth - Vin_DC - 0.05

        x_upper = min(vov_max * 0.85, vov_max_gate)
        x_lower = 0.1

        if x_upper <= x_lower:
            continue

        VOV     = rng.uniform(x_lower, x_upper)
        VGS     = Vth + VOV
        VG_bias = VGS + Vin_DC
        ID      = 0.5 * kn * VOV ** 2
        VD      = VDD - ID * RD
        VDS     = VD - Vin_DC

        if not (VDS >= VOV and VD > Vin_DC and VD < VDD and VG_bias < VDD):
            continue

        sample_id = (
            f"cg_resistor_{seed}"
            if seed is not None
            else f"cg_resistor_{uuid.uuid4().hex[:8]}"
        )

        circuit = Circuit(
            sample_id=sample_id,
            incidence=_build_cg_resistor_incidence(),
            devices={
                "M1": Device(
                    id="M1", kind="nmos", terminals=["D", "G", "S", "B"],
                    metadata={"W": W, "L": _FIXED_L},
                ),
                "RD": Device(
                    id="RD", kind="resistor", terminals=["a", "b"],
                    metadata={"value": RD},
                ),
            },
            nodes={
                "VDD":     Node(id="VDD",     role="supply", voltage_dc=VDD),
                "GND":     Node(id="GND",     role="ground", voltage_dc=0.0),
                "vo":      Node(id="vo",      role="output", voltage_dc=None),
                "vin":     Node(id="vin",     role="input",  voltage_dc=Vin_DC),
                "VG_bias": Node(id="VG_bias", role="supply", voltage_dc=VG_bias),
            },
        )

        given: dict[str, float] = {
            "VDD":     VDD,
            "VG_bias": VG_bias,
            "Vin_DC":  Vin_DC,
            "Vth":     Vth,
            "kn":      kn,
            "lambda":  lam,
            "RD":      RD,
            "CL":      CL,
            "Cgd":     Cgd,
            "mun_Cox": mun_Cox,
            "W":       W,
            "L":       _FIXED_L,
        }

        return circuit, given

    raise ValueError(
        f"generate_cg_resistor_circuit: no feasible parameters found after "
        f"{_MAX_ATTEMPTS} attempts."
    )


# ---------------------------------------------------------------------------
# Cascode (CS + CG stacked) + resistor drain load
# ---------------------------------------------------------------------------

def generate_cascode_resistor_circuit(
    seed: int | None = None,
) -> tuple[Circuit, dict[str, float]]:
    """Randomly generate an NMOS cascode (M1=CS, M2=CG) + resistor drain load.

    Both devices share the same W/L (kn1=kn2, Vth1=Vth2, lambda1=lambda2).
    vx is sampled from the safe window between the two saturation boundaries.
    Returns (circuit, given) ready for CASCODE_RESISTOR_TEMPLATE.
    """
    rng = random.Random(seed)

    for _attempt in range(_MAX_ATTEMPTS):
        VDD      = rng.uniform(1.8, 3.3)   # extra headroom for two-transistor stack
        mun_Cox  = rng.uniform(50e-6, 500e-6)
        WL_ratio = rng.uniform(2.0, 30.0)   # conservative W/L for cascode
        Vth      = rng.uniform(0.3, 0.6)    # lower ceiling for cascode headroom
        RD       = rng.uniform(1_000.0, 30_000.0)
        lam      = rng.uniform(0.01, 0.05)  # CLM needed for Rout boost
        CL       = rng.uniform(10e-15, 500e-15)
        Cgd      = rng.uniform(1e-15, 20e-15)

        kn = mun_Cox * WL_ratio
        W  = WL_ratio * _FIXED_L

        # VOV_max for cascode: need vo > 1.2·VOV1 + 1.2·VOV2 = 2.4·VOV (same kn)
        # vo = VDD − 0.5·kn·RD·VOV²
        # → 0.5·kn·RD·VOV² + 2.4·VOV − VDD < 0
        # Positive root: VOV_max = (−2.4 + sqrt(2.4²+ 4·a·VDD)) / (2·a), a=0.5·kn·RD
        a    = 0.5 * kn * RD
        disc = 2.4 ** 2 + 4.0 * a * VDD
        if disc <= 0:
            continue

        vov_max      = (-2.4 + math.sqrt(disc)) / (2.0 * a)
        vov_max_vin  = VDD - Vth - 0.1   # keeps Vin_DC = VGS1 < VDD

        x_upper = min(vov_max * 0.85, vov_max_vin)
        x_lower = 0.1
        if x_upper <= x_lower:
            continue

        VOV = rng.uniform(x_lower, x_upper)
        ID  = 0.5 * kn * VOV ** 2
        vo  = VDD - ID * RD

        # M2 Q-point (same kn → VOV2 = VOV1)
        VOV2    = math.sqrt(2.0 * ID / kn)   # ≈ VOV when kn1 = kn2
        VGS2    = Vth + VOV2

        # vx window: M1 saturation (vx ≥ VOV·1.2) and M2 saturation (vo−vx ≥ VOV2·1.2)
        vx_lo = VOV * 1.2
        vx_hi = vo - VOV2 * 1.2
        if vx_hi <= vx_lo:
            continue

        vx       = rng.uniform(vx_lo, vx_hi)
        VG2_bias = vx + VGS2
        Vin_DC   = Vth + VOV   # M1 gate bias (VGS1, grounded source)

        if not (VG2_bias < VDD and Vin_DC < VDD and vx > 0):
            continue

        sample_id = (
            f"cascode_resistor_{seed}"
            if seed is not None
            else f"cascode_resistor_{uuid.uuid4().hex[:8]}"
        )

        circuit = Circuit(
            sample_id=sample_id,
            incidence=_build_cascode_resistor_incidence(),
            devices={
                "M1": Device(
                    id="M1", kind="nmos", terminals=["D", "G", "S", "B"],
                    metadata={"W": W, "L": _FIXED_L},
                ),
                "M2": Device(
                    id="M2", kind="nmos", terminals=["D", "G", "S", "B"],
                    metadata={"W": W, "L": _FIXED_L},
                ),
                "RD": Device(
                    id="RD", kind="resistor", terminals=["a", "b"],
                    metadata={"value": RD},
                ),
            },
            nodes={
                "VDD":      Node(id="VDD",      role="supply",   voltage_dc=VDD),
                "GND":      Node(id="GND",      role="ground",   voltage_dc=0.0),
                "vo":       Node(id="vo",       role="output",   voltage_dc=None),
                "vx":       Node(id="vx",       role="internal", voltage_dc=None),
                "vin":      Node(id="vin",      role="input",    voltage_dc=Vin_DC),
                "VG2_bias": Node(id="VG2_bias", role="supply",   voltage_dc=VG2_bias),
            },
        )

        given: dict[str, float] = {
            "VDD":      VDD,
            "Vin_DC":   Vin_DC,
            "VG2_bias": VG2_bias,
            "Vth1":     Vth,
            "Vth2":     Vth,
            "kn1":      kn,
            "kn2":      kn,
            "lambda1":  lam,
            "lambda2":  lam,
            "RD":       RD,
            "CL":       CL,
            "Cgd":      Cgd,
            "mun_Cox":  mun_Cox,
            "W":        W,
            "L":        _FIXED_L,
        }

        return circuit, given

    raise ValueError(
        f"generate_cascode_resistor_circuit: no feasible parameters found after "
        f"{_MAX_ATTEMPTS} attempts."
    )


# ---------------------------------------------------------------------------
# Topology-agnostic dispatcher
# ---------------------------------------------------------------------------

def generate_random_circuit(
    seed: int | None = None,
) -> tuple[Circuit, dict[str, float], str]:
    """Pick a random topology and generate one feasible circuit.

    Returns:
        circuit:  Circuit object.
        given:    Parameter dict ready for the corresponding DAG template.
        topo_key: String key into the topology registry (e.g. "cs_resistor").
    """
    rng = random.Random(seed)
    topo_key = rng.choice(_TOPOLOGY_KEYS)

    # Derive a deterministic sub-seed so the sub-generator is also reproducible.
    sub_seed: int | None = rng.randint(0, 2 ** 32 - 1) if seed is not None else None

    _GEN = {
        "cs_resistor":       generate_cs_resistor_circuit,
        "sf_resistor":       generate_sf_resistor_circuit,
        "cs_current_source": generate_cs_current_source_circuit,
        "cg_resistor":       generate_cg_resistor_circuit,
        "cascode_resistor":  generate_cascode_resistor_circuit,
    }
    circuit, given = _GEN[topo_key](seed=sub_seed)
    return circuit, given, topo_key
