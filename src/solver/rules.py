"""Layer 1 of the reasoning DAG: pure rule functions.

See ADR-006 for architecture overview. Each function encodes one
physics formula and returns a RuleResult with the numerical value,
LaTeX formula, justification, and any approximations applied.

Rules are topology-agnostic: they do not know what circuit they
operate in. They only perform arithmetic on scalar inputs.
"""

import math
from dataclasses import dataclass, field


@dataclass(frozen=True)
class RuleResult:
    value: float
    formula_latex: str
    justification: str
    approximations: list[str] = field(default_factory=list)


# ---------------------------------------------------------------------------
# Step 3 — Q-point (large-signal DC analysis)
# ---------------------------------------------------------------------------

def rule_vgs_grounded_source(VG_DC: float) -> RuleResult:
    """VGS = VG_DC (specialization for VS = 0, grounded source in CS topology)"""
    return RuleResult(
        value=VG_DC,
        formula_latex=r"V_{GS} = V_G - V_S = V_G \quad (V_S = 0)",
        justification=(
            "Gate-source voltage with grounded source terminal: "
            "VS = 0 in CS topology, so VGS equals the DC gate voltage directly."
        ),
        approximations=[],
    )


def rule_overdrive_voltage(VGS: float, Vth: float) -> RuleResult:
    """VOV = VGS - Vth"""
    return RuleResult(
        value=VGS - Vth,
        formula_latex=r"V_{OV} = V_{GS} - V_{th}",
        justification=(
            "Overdrive voltage: the gate-source bias above threshold that "
            "controls drain current in saturation."
        ),
        approximations=[],
    )


def rule_saturation_current_no_clm(kn: float, VOV: float) -> RuleResult:
    """ID = (1/2) * kn * VOV^2  (channel-length modulation ignored, lambda=0)"""
    return RuleResult(
        value=0.5 * kn * VOV ** 2,
        formula_latex=r"I_D = \frac{1}{2} k_n V_{OV}^2",
        justification=(
            "Square-law saturation current for NMOS; channel-length "
            "modulation term dropped because lambda = 0."
        ),
        approximations=["channel-length modulation ignored (lambda = 0)"],
    )


def rule_saturation_current_with_clm(
    kn: float, VOV: float, lam: float, VDS: float
) -> RuleResult:
    """ID = (1/2) * kn * VOV^2 * (1 + lambda * VDS)"""
    return RuleResult(
        value=0.5 * kn * VOV ** 2 * (1.0 + lam * VDS),
        formula_latex=r"I_D = \frac{1}{2} k_n V_{OV}^2 (1 + \lambda V_{DS})",
        justification=(
            "Square-law saturation current including channel-length "
            "modulation; models finite output resistance of the MOSFET."
        ),
        approximations=[],
    )


def rule_kvl_drain_voltage(VDD: float, ID: float, RD: float) -> RuleResult:
    """VD = VDD - ID * RD  (KVL along supply → drain resistor → drain node)"""
    return RuleResult(
        value=VDD - ID * RD,
        formula_latex=r"V_D = V_{DD} - I_D R_D",
        justification=(
            "KVL from supply rail through drain resistor: drain voltage "
            "equals supply minus the resistive drop."
        ),
        approximations=[],
    )


def rule_vds_grounded_source(VD: float) -> RuleResult:
    """VDS = VD  (specialization for VS = 0, grounded source)"""
    return RuleResult(
        value=VD,
        formula_latex=r"V_{DS} = V_D - V_S = V_D \quad (V_S = 0)",
        justification=(
            "Source is tied to ground (VS = 0), so VDS reduces to VD."
        ),
        approximations=[],
    )


# ---------------------------------------------------------------------------
# Step 4 — Q-point verification
# ---------------------------------------------------------------------------

def rule_saturation_check(VDS: float, VOV: float) -> RuleResult:
    """Returns 1.0 if NMOS saturation condition VDS >= VOV is satisfied, else 0.0."""
    passes = 1.0 if VDS >= VOV else 0.0
    return RuleResult(
        value=passes,
        formula_latex=r"V_{DS} \geq V_{OV} \Rightarrow \text{saturation}",
        justification=(
            "NMOS saturation requires VDS >= VGS - Vth = VOV; "
            "returns 1.0 if the condition holds, 0.0 if the device is in triode."
        ),
        approximations=[],
    )


# ---------------------------------------------------------------------------
# Step 5 — Small-signal parameter extraction
# ---------------------------------------------------------------------------

def rule_transconductance(kn: float, VOV: float) -> RuleResult:
    """gm = kn * VOV  (= dID/dVGS evaluated at the Q-point)"""
    return RuleResult(
        value=kn * VOV,
        formula_latex=r"g_m = k_n V_{OV}",
        justification=(
            "Small-signal transconductance: partial derivative of drain "
            "current with respect to VGS, evaluated at the Q-point in saturation."
        ),
        approximations=[],
    )


def rule_output_resistance(lam: float, ID: float) -> RuleResult:
    """ro = 1 / (lambda * ID); returns float('inf') when lambda = 0."""
    if lam == 0.0:
        ro = float("inf")
    else:
        ro = 1.0 / (lam * ID)
    return RuleResult(
        value=ro,
        formula_latex=r"r_o = \frac{1}{\lambda I_D}",
        justification=(
            "Small-signal output resistance from channel-length modulation; "
            "infinite output resistance when CLM is disabled (lambda = 0)."
        ),
        approximations=(
            ["infinite output resistance: CLM disabled (lambda = 0)"]
            if lam == 0.0
            else []
        ),
    )


# ---------------------------------------------------------------------------
# Step 6 — Low-frequency gain and impedances
# ---------------------------------------------------------------------------

def rule_parallel_resistance(R1: float, R2: float) -> RuleResult:
    """Rpar = R1 || R2; handles inf correctly (inf || R = R)."""
    if math.isinf(R1) and math.isinf(R2):
        rpar = float("inf")
    elif math.isinf(R1):
        rpar = R2
    elif math.isinf(R2):
        rpar = R1
    else:
        rpar = (R1 * R2) / (R1 + R2)
    return RuleResult(
        value=rpar,
        formula_latex=r"R_{\parallel} = \frac{R_1 R_2}{R_1 + R_2}",
        justification=(
            "Two resistances in parallel; if either is infinite the "
            "parallel combination equals the finite one."
        ),
        approximations=[],
    )


def rule_cs_voltage_gain(gm: float, Rout: float) -> RuleResult:
    """Av = -gm * Rout  (low-frequency CS voltage gain)"""
    return RuleResult(
        value=-gm * Rout,
        formula_latex=r"A_v = -g_m R_{out}",
        justification=(
            "Common-source low-frequency voltage gain: the transconductance "
            "current flows through the total output resistance, with sign "
            "inversion due to the common-source topology."
        ),
        approximations=[],
    )


# ---------------------------------------------------------------------------
# Step 7 — High-frequency capacitances (Miller decomposition at output node)
# ---------------------------------------------------------------------------

def rule_miller_output_capacitance(CL: float, Cgd: float, Av: float) -> RuleResult:
    """Cout = CL + Cgd * (1 - 1/Av)  (output-node Miller-equivalent capacitance).

    Guard: if |Av| < 1e-10 treat as Av → 0; Cout ≈ CL + Cgd.
    """
    if abs(Av) < 1.0e-10:
        cout = CL + Cgd
        approx = ["Av ≈ 0: Miller factor (1 - 1/Av) approximated as 1"]
    else:
        cout = CL + Cgd * (1.0 - 1.0 / Av)
        approx = []
    return RuleResult(
        value=cout,
        formula_latex=r"C_{out} = C_L + C_{gd}\!\left(1 - \frac{1}{A_v}\right)",
        justification=(
            "Miller decomposition at the output node: Cgd appears as "
            "Cgd*(1 - 1/Av) at the drain, added to the explicit load "
            "capacitor CL to give the total output-node capacitance."
        ),
        approximations=approx,
    )


# ---------------------------------------------------------------------------
# Step 8 — Poles
# ---------------------------------------------------------------------------

def rule_rc_pole(R: float, C: float) -> RuleResult:
    """omega_p = 1 / (R * C)  [rad/s]"""
    return RuleResult(
        value=1.0 / (R * C),
        formula_latex=r"\omega_p = \frac{1}{RC}",
        justification=(
            "Single-pole RC time-constant estimate: the pole angular "
            "frequency is the reciprocal of the product of the equivalent "
            "resistance and capacitance seen at the node."
        ),
        approximations=[],
    )


def rule_omega_to_hz(omega: float) -> RuleResult:
    """f = omega / (2 * pi)  [Hz]"""
    return RuleResult(
        value=omega / (2.0 * math.pi),
        formula_latex=r"f = \frac{\omega}{2\pi}",
        justification=(
            "Convert pole location from radians per second to hertz."
        ),
        approximations=[],
    )


# ---------------------------------------------------------------------------
# Utility
# ---------------------------------------------------------------------------

def rule_av_to_db(Av: float) -> RuleResult:
    """Av_dB = 20 * log10(|Av|)"""
    return RuleResult(
        value=20.0 * math.log10(abs(Av)),
        formula_latex=r"A_{v,\mathrm{dB}} = 20 \log_{10} |A_v|",
        justification=(
            "Convert voltage gain magnitude to decibels using the "
            "standard 20 log10 definition."
        ),
        approximations=[],
    )
