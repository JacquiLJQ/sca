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
    """gm = kn * VOV  (CLM omitted; use rule_transconductance_clm when VDS is available)"""
    return RuleResult(
        value=kn * VOV,
        formula_latex=r"g_m = k_n V_{OV}",
        justification=(
            "Small-signal transconductance: partial derivative of drain "
            "current with respect to VGS, evaluated at the Q-point in saturation."
        ),
        approximations=["channel-length modulation omitted from gm (lambda*VDS factor dropped)"],
    )


def rule_transconductance_clm(kn: float, VOV: float, lam: float, VDS: float) -> RuleResult:
    """gm = kn * VOV * (1 + lambda * VDS)  — full CLM-corrected transconductance.

    Matches ngspice Level-1 definition: gm = KP*(W/L)*(VGS-Vth)*(1+LAMBDA*VDS).
    """
    clm = 1.0 + lam * VDS
    return RuleResult(
        value=kn * VOV * clm,
        formula_latex=r"g_m = k_n V_{OV} (1 + \lambda V_{DS})",
        justification=(
            "Small-signal transconductance including channel-length modulation: "
            "partial derivative of ID = (kn/2)·VOV²·(1+λ·VDS) with respect to VGS. "
            "Matches the ngspice Level-1 model (KP·W/L·(VGS−Vth)·(1+LAMBDA·VDS))."
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


# ---------------------------------------------------------------------------
# Source Follower — Step 3: Q-point rules
# ---------------------------------------------------------------------------

def rule_sf_id_quadratic(
    kn: float, VG_DC: float, Vth: float, Rs_load: float
) -> RuleResult:
    """Drain current for SF with source resistor; solves ID-VS feedback quadratic.

    From ID = (1/2)*kn*(VG_DC - Vth - ID*Rs_load)^2 the discriminant simplifies
    to 1 + 2*kn*(VG_DC-Vth)*Rs_load; the smaller root is physically correct
    (gives VS > 0, VOV in valid range).  Lambda is ignored per ADR-003.
    """
    b = VG_DC - Vth
    disc = 1.0 + 2.0 * kn * b * Rs_load
    if disc < 0.0:
        raise ValueError(
            f"SF quadratic has no real solution "
            f"(disc={disc:.4g}): device is below threshold or circuit is infeasible."
        )
    id_val = (kn * b * Rs_load + 1.0 - math.sqrt(disc)) / (kn * Rs_load**2)
    return RuleResult(
        value=id_val,
        formula_latex=(
            r"I_D = \frac{k_n(V_G-V_{th})R_S + 1 "
            r"- \sqrt{1 + 2k_n(V_G-V_{th})R_S}}{k_n R_S^2}"
        ),
        justification=(
            "SF Q-point: VS = ID·Rs_load creates feedback between ID and VGS. "
            "Substituting VGS = VG_DC − VS into ID = (1/2)·kn·(VGS−Vth)² yields "
            "a quadratic whose discriminant simplifies to 1 + 2·kn·(VG−Vth)·Rs. "
            "The smaller root is taken (VS > 0 and VOV physically valid). "
            "Lambda ignored per first-order Q-point approximation (ADR-003)."
        ),
        approximations=["channel-length modulation ignored (lambda = 0) for Q-point solve"],
    )


def rule_vs_from_id(ID: float, Rs_load: float) -> RuleResult:
    """VS = ID * Rs_load  (KVL at SF source node)"""
    return RuleResult(
        value=ID * Rs_load,
        formula_latex=r"V_S = I_D R_S",
        justification=(
            "Source-node KVL: the only path from source to ground is Rs_load, "
            "so VS equals the resistive drop ID·Rs_load."
        ),
        approximations=[],
    )


def rule_vgs_nonzero_source(VG_DC: float, VS: float) -> RuleResult:
    """VGS = VG_DC - VS  (general; VS != 0 unlike CS grounded-source case)"""
    return RuleResult(
        value=VG_DC - VS,
        formula_latex=r"V_{GS} = V_G - V_S",
        justification=(
            "Gate-source voltage with floating source: VS = ID·Rs_load is "
            "non-zero in SF topology, so VGS = VG_DC − VS rather than VG_DC."
        ),
        approximations=[],
    )


def rule_vd_connected_to_supply(VDD: float) -> RuleResult:
    """VD = VDD  (SF drain tied directly to the supply rail, no drain resistor)"""
    return RuleResult(
        value=VDD,
        formula_latex=r"V_D = V_{DD}",
        justification=(
            "Drain tied directly to supply rail in SF topology, so VD = VDD."
        ),
        approximations=[],
    )


def rule_vds_sf(VDD: float, VS: float) -> RuleResult:
    """VDS = VDD - VS  (SF drain tied directly to VDD, no drain resistor)"""
    return RuleResult(
        value=VDD - VS,
        formula_latex=r"V_{DS} = V_{DD} - V_S",
        justification=(
            "SF drain is connected directly to VDD (no drain resistor), "
            "so VDS = VDD − VS."
        ),
        approximations=[],
    )


# ---------------------------------------------------------------------------
# Source Follower — Step 6: Gain and impedance rules
# ---------------------------------------------------------------------------

def rule_one_over_gm(gm: float) -> RuleResult:
    """Returns 1/gm, the intrinsic SF output impedance looking into the source."""
    return RuleResult(
        value=1.0 / gm,
        formula_latex=r"\frac{1}{g_m}",
        justification=(
            "Intrinsic small-signal resistance looking into the source terminal "
            "of the SF stage; typically dominates Rout because Rs_load and ro "
            "are much larger than 1/gm."
        ),
        approximations=[],
    )


def rule_sf_voltage_gain(gm: float, Req: float) -> RuleResult:
    """Av = gm * Req / (1 + gm * Req)  — non-inverting SF gain, always < 1."""
    av = gm * Req / (1.0 + gm * Req)
    return RuleResult(
        value=av,
        formula_latex=r"A_v = \frac{g_m R_{eq}}{1 + g_m R_{eq}}",
        justification=(
            "Source-follower low-frequency voltage gain: non-inverting (positive) "
            "and always < 1. Req = Rs_load ∥ ro is the equivalent resistance at "
            "the source node. The (1 + gm·Req) denominator comes from the "
            "negative feedback of the source voltage back onto VGS."
        ),
        approximations=[],
    )


# ---------------------------------------------------------------------------
# Source Follower — Step 7: High-frequency output capacitance
# ---------------------------------------------------------------------------

def rule_sf_output_capacitance(CL: float) -> RuleResult:
    """Cout = CL  (Cgs bootstrap neglected; only explicit load capacitor counted)."""
    return RuleResult(
        value=CL,
        formula_latex=r"C_{out} = C_L",
        justification=(
            "SF output-node capacitance: Cgs appears bootstrapped because both "
            "its terminals move nearly in phase (Av ≈ 1), so its net contribution "
            "to the output node is negligible. Only the explicit load capacitor "
            "CL is counted as the dominant output capacitance."
        ),
        approximations=["Cgs bootstrap effect neglected; output capacitance approximated as CL only"],
    )


# ---------------------------------------------------------------------------
# CS + ideal current source load — Step 3: Q-point (reverse solve)
#
# Solve order is inverted vs CS+resistor: Iload forces ID, VDS_target gives
# VDS, then VOV/VGS/VG_DC are back-calculated from the square law.
# ---------------------------------------------------------------------------

def rule_id_from_current_source(Iload: float) -> RuleResult:
    """ID = Iload  (ideal current source forces drain bias current directly)."""
    return RuleResult(
        value=Iload,
        formula_latex=r"I_D = I_{load}",
        justification=(
            "Ideal current source load forces the drain current to equal Iload "
            "regardless of VDS. The Q-point current is therefore a given, not "
            "derived from VGS via the square law."
        ),
        approximations=[],
    )


def rule_vds_from_target(VDS_target: float) -> RuleResult:
    """VDS = VDS_target  (design-specified operating VDS)."""
    return RuleResult(
        value=VDS_target,
        formula_latex=r"V_{DS} = V_{DS,\mathrm{target}}",
        justification=(
            "VDS is set by design choice (VDS_target): the gate bias VG_DC is "
            "selected so that the transistor operates at this drain-source voltage."
        ),
        approximations=[],
    )


def rule_vov_from_id_clm(ID: float, kn: float, lam: float, VDS: float) -> RuleResult:
    """VOV = sqrt(2*ID / (kn*(1+lambda*VDS)))  — reverse square-law with CLM."""
    vov = math.sqrt(2.0 * ID / (kn * (1.0 + lam * VDS)))
    return RuleResult(
        value=vov,
        formula_latex=r"V_{OV} = \sqrt{\frac{2 I_D}{k_n (1 + \lambda V_{DS})}}",
        justification=(
            "Overdrive voltage back-calculated from the known bias current ID: "
            "invert ID = (1/2)·kn·VOV²·(1+λ·VDS) to solve for VOV. "
            "Includes channel-length modulation because lambda ≠ 0 in this topology."
        ),
        approximations=[],
    )


def rule_vgs_from_vov(VOV: float, Vth: float) -> RuleResult:
    """VGS = VOV + Vth  (inverse of rule_overdrive_voltage)."""
    return RuleResult(
        value=VOV + Vth,
        formula_latex=r"V_{GS} = V_{OV} + V_{th}",
        justification=(
            "Gate-source voltage recovered from overdrive: VGS = VOV + Vth, "
            "the algebraic inverse of VOV = VGS − Vth."
        ),
        approximations=[],
    )


def rule_vg_dc_grounded_source(VGS: float) -> RuleResult:
    """VG_DC = VGS  (source grounded: VS=0, so VG_DC = VGS + VS = VGS)."""
    return RuleResult(
        value=VGS,
        formula_latex=r"V_{G,\mathrm{DC}} = V_{GS} \quad (V_S = 0)",
        justification=(
            "Source terminal is grounded (VS = 0) in CS topology, so the "
            "required DC gate voltage equals VGS directly."
        ),
        approximations=[],
    )


def rule_vd_from_vds_grounded_source(VDS: float) -> RuleResult:
    """VD = VDS  (source grounded: VS=0, so VD = VDS + VS = VDS)."""
    return RuleResult(
        value=VDS,
        formula_latex=r"V_D = V_{DS} \quad (V_S = 0)",
        justification=(
            "Source terminal is grounded (VS = 0) in CS topology, so "
            "drain voltage VD equals VDS directly."
        ),
        approximations=[],
    )


# ---------------------------------------------------------------------------
# CS + ideal current source load — Step 6: Output resistance
# ---------------------------------------------------------------------------

def rule_rout_current_source_load(ro: float) -> RuleResult:
    """Rout = ro  (ideal current source has infinite small-signal resistance)."""
    return RuleResult(
        value=ro,
        formula_latex=r"R_{out} = r_o",
        justification=(
            "Ideal current source load has infinite small-signal output resistance. "
            "Rout = ro ∥ ∞ = ro: the total output resistance at the drain node "
            "collapses to the transistor's own output resistance."
        ),
        approximations=[],
    )


# ---------------------------------------------------------------------------
# Common Gate — Step 3: Q-point rules
# ---------------------------------------------------------------------------

def rule_vgs_cg(VG_bias: float, Vin_DC: float) -> RuleResult:
    """VGS = VG_bias - Vin_DC  (gate at fixed bias, source at input DC level)."""
    return RuleResult(
        value=VG_bias - Vin_DC,
        formula_latex=r"V_{GS} = V_{G,\mathrm{bias}} - V_{in,\mathrm{DC}}",
        justification=(
            "CG topology: gate is held at a fixed DC bias VG_bias while the "
            "source terminal is driven by the input signal's DC operating point "
            "Vin_DC, so VGS = VG_bias − Vin_DC."
        ),
        approximations=[],
    )


def rule_vds_nonzero_source(VD: float, VS: float) -> RuleResult:
    """VDS = VD - VS  (general form; VS != 0)."""
    return RuleResult(
        value=VD - VS,
        formula_latex=r"V_{DS} = V_D - V_S",
        justification=(
            "Drain-source voltage: general KVL subtraction of source voltage "
            "from drain voltage. Applies when VS ≠ 0 (e.g. CG, cascode upper device)."
        ),
        approximations=[],
    )


# ---------------------------------------------------------------------------
# Common Gate — Step 6: Gain and input resistance
# ---------------------------------------------------------------------------

def rule_cg_voltage_gain(gm: float, Rout: float) -> RuleResult:
    """Av = +gm * Rout  (non-inverting CG voltage gain)."""
    return RuleResult(
        value=gm * Rout,
        formula_latex=r"A_v = +g_m R_{out}",
        justification=(
            "Common-gate low-frequency voltage gain: non-inverting (positive) "
            "because the input current flows into the source and out of the drain "
            "in the same direction, unlike CS where the sign is inverted. "
            "Rout = RD ∥ ro is the total resistance at the drain node."
        ),
        approximations=[],
    )


def rule_rin_cg(gm: float) -> RuleResult:
    """Rin = 1/gm  (CG small-signal input resistance looking into source terminal)."""
    return RuleResult(
        value=1.0 / gm,
        formula_latex=r"R_{in} = \frac{1}{g_m}",
        justification=(
            "CG input resistance: looking into the source terminal with gate "
            "AC-grounded, the small-signal resistance is 1/gm (ignoring ro). "
            "This low input impedance is the defining characteristic of the CG stage "
            "and makes it useful as a current buffer and in cascode configurations."
        ),
        approximations=["ro neglected in Rin expression (1/gm || ro ≈ 1/gm when gm·ro >> 1)"],
    )


# ---------------------------------------------------------------------------
# Cascode — Step 3: Q-point rules
# ---------------------------------------------------------------------------

def rule_vov_from_id_no_clm(ID: float, kn: float) -> RuleResult:
    """VOV = sqrt(2*ID / kn)  — reverse square-law, lambda=0 approximation.

    Used when VDS is not yet resolved (e.g., cascode M2 Q-point: ID is known
    from M1 but VDS2 cannot be computed until vx is known, which requires VOV2).
    """
    vov = math.sqrt(2.0 * ID / kn)
    return RuleResult(
        value=vov,
        formula_latex=r"V_{OV} = \sqrt{\frac{2 I_D}{k_n}}",
        justification=(
            "Overdrive voltage back-calculated from bias current ID using the "
            "first-order square law (lambda = 0): invert ID = (1/2)·kn·VOV² "
            "to get VOV = sqrt(2·ID/kn). Used when VDS is not yet available "
            "(e.g., cascode upper device Q-point). ADR-003 first-order approximation."
        ),
        approximations=["channel-length modulation ignored (lambda = 0) for Q-point solve"],
    )


def rule_source_voltage_from_gate_vgs(VG_bias: float, VGS: float) -> RuleResult:
    """VS = VG_bias - VGS  (source node voltage from gate bias and VGS)."""
    return RuleResult(
        value=VG_bias - VGS,
        formula_latex=r"V_S = V_{G,\mathrm{bias}} - V_{GS}",
        justification=(
            "Source node voltage obtained by inverting VGS = VG − VS: "
            "given the gate bias and VGS, VS = VG_bias − VGS. "
            "Used in cascode to find the intermediate node vx = VG2_bias − VGS2."
        ),
        approximations=[],
    )


# ---------------------------------------------------------------------------
# Cascode — Step 6: Output resistance
# ---------------------------------------------------------------------------

def rule_cascode_output_resistance(gm2: float, ro1: float, ro2: float) -> RuleResult:
    """Rout_cascode = ro2 * (1 + gm2 * ro1)  — cascode output resistance boost."""
    rout = ro2 * (1.0 + gm2 * ro1)
    return RuleResult(
        value=rout,
        formula_latex=r"R_{out,\mathrm{casc}} = r_{o2}(1 + g_{m2} r_{o1})",
        justification=(
            "Cascode output resistance: the CG upper device (M2) sees ro1 as a "
            "source-degeneration resistance, boosting its output resistance by "
            "factor (1 + gm2·ro1). For typical gm2·ro1 >> 1, this approximates "
            "gm2·ro2·ro1, the intrinsic gain of M2 times ro1."
        ),
        approximations=[],
    )


# ---------------------------------------------------------------------------
# Multi-stage — Step 6: inter-stage loading analysis and cascade gain
# ---------------------------------------------------------------------------

def rule_rin_infinite() -> RuleResult:
    """Rin = ∞  — MOSFET gate input resistance (no gate current)."""
    return RuleResult(
        value=float("inf"),
        formula_latex=r"R_{in} = \infty",
        justification=(
            "MOSFET gate input resistance is effectively infinite at low frequency: "
            "the gate oxide prevents DC gate current."
        ),
        approximations=[],
    )


def rule_loading_factor(Rout_prev: float, Rin_next: float) -> RuleResult:
    """loading_factor = Rin_next / (Rout_prev + Rin_next); 1.0 when Rin_next → ∞."""
    if math.isinf(Rin_next):
        factor = 1.0
    else:
        factor = Rin_next / (Rout_prev + Rin_next)
    return RuleResult(
        value=factor,
        formula_latex=r"\alpha = \frac{R_{in,next}}{R_{out,prev} + R_{in,next}}",
        justification=(
            "Voltage-divider loading factor between cascaded stages: ratio of the "
            "next stage's input impedance to the total series resistance. "
            "Approaches 1 when Rin_next >> Rout_prev (negligible loading)."
        ),
        approximations=(
            ["loading factor = 1 (Rin_next = ∞, no loading)"]
            if math.isinf(Rin_next)
            else []
        ),
    )


def rule_loaded_gain(Av_unloaded: float, loading_factor: float) -> RuleResult:
    """Av_loaded = Av_unloaded * loading_factor."""
    return RuleResult(
        value=Av_unloaded * loading_factor,
        formula_latex=r"A_{v,\mathrm{loaded}} = A_v \cdot \alpha",
        justification=(
            "Effective stage gain after accounting for the voltage-divider "
            "attenuation caused by the next stage's input impedance loading "
            "the current stage's output."
        ),
        approximations=[],
    )


def rule_cascade_gain(Av1: float, Av2: float) -> RuleResult:
    """Av_total = Av1 * Av2  — gain of two cascaded stages."""
    return RuleResult(
        value=Av1 * Av2,
        formula_latex=r"A_{v,\mathrm{total}} = A_{v1} \cdot A_{v2}",
        justification=(
            "Total voltage gain of cascaded stages is the product of individual "
            "stage gains (assuming ideal inter-stage isolation)."
        ),
        approximations=[],
    )
