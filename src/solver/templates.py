"""Layer 3 of the reasoning DAG: topology-specific templates.

Each template is a list of DAGNode defining the analysis sequence
for one topology. Phase 1 provides hand-written templates; Phase 3
will auto-generate them from incidence matrix annotations (ADR-006).

Template invariant: input_ids of each node must refer to either
(a) output_symbol of a preceding node, or (b) a key in the given dict.
"""

from src.solver.dag_executor import DAGNode


# ---------------------------------------------------------------------------
# Phase 1 — CS with resistor load (NMOS common-source, RD to VDD)
#
# Required given dict keys:
#   VG_DC   : float  — DC gate voltage [V]
#   Vth     : float  — MOSFET threshold voltage [V]
#   kn      : float  — effective transconductance parameter mun_Cox*(W/L) [A/V²]
#   VDD     : float  — supply voltage [V]
#   RD      : float  — drain resistor [Ω]
#   lambda  : float  — channel-length modulation coefficient [V⁻¹]; 0 to disable CLM
#   CL      : float  — explicit load capacitance [F]
#   Cgd     : float  — gate-drain overlap capacitance [F]
#
# Note: "lambda" is used as a string key (not a Python keyword here).
# Note: kn = mun_Cox * (W/L) must be pre-computed by Module B before
#       passing given to execute_reasoning_dag.
# ---------------------------------------------------------------------------

CS_RESISTOR_TEMPLATE: list[DAGNode] = [
    # Step 3: Q-point (large-signal DC analysis)
    DAGNode("VGS",  3, "rule_vgs_grounded_source",      ["VG_DC"],           "VGS"),
    DAGNode("VOV",  3, "rule_overdrive_voltage",         ["VGS", "Vth"],      "VOV"),
    DAGNode("ID",   3, "rule_saturation_current_no_clm", ["kn", "VOV"],       "ID"),
    DAGNode("VD",   3, "rule_kvl_drain_voltage",         ["VDD", "ID", "RD"], "VD"),
    DAGNode("VDS",  3, "rule_vds_grounded_source",       ["VD"],              "VDS"),

    # Step 4: Q-point verification
    DAGNode("sat_check", 4, "rule_saturation_check",     ["VDS", "VOV"],      "sat_ok"),

    # Step 5: Small-signal parameter extraction
    DAGNode("gm",   5, "rule_transconductance",          ["kn", "VOV"],       "gm"),
    DAGNode("ro",   5, "rule_output_resistance",         ["lambda", "ID"],    "ro"),

    # Step 6: Low-frequency gain and output resistance
    DAGNode("Rout", 6, "rule_parallel_resistance",       ["RD", "ro"],        "Rout"),
    DAGNode("Av",   6, "rule_cs_voltage_gain",           ["gm", "Rout"],      "Av"),
    DAGNode("Av_dB",6, "rule_av_to_db",                  ["Av"],              "Av_dB"),

    # Step 7: High-frequency output capacitance (Miller decomposition)
    DAGNode("Cout", 7, "rule_miller_output_capacitance", ["CL", "Cgd", "Av"], "Cout"),

    # Step 8: Dominant pole at output node
    DAGNode("p1_omega", 8, "rule_rc_pole",               ["Rout", "Cout"],    "p1_omega"),
    DAGNode("p1_Hz",    8, "rule_omega_to_hz",           ["p1_omega"],        "p1_Hz"),
]


# ---------------------------------------------------------------------------
# Phase 2 — SF with resistor source load (NMOS source follower, Rs_load to GND)
#
# Required given dict keys:
#   VDD      : float  — supply voltage [V]
#   VG_DC    : float  — DC gate voltage [V]
#   Vth      : float  — MOSFET threshold voltage [V]
#   kn       : float  — effective transconductance parameter mun_Cox*(W/L) [A/V²]
#   Rs_load  : float  — source resistor [Ω]; drain is tied directly to VDD (no RD)
#   lambda   : float  — channel-length modulation coefficient [V⁻¹]; 0 to disable CLM
#   CL       : float  — explicit load capacitance [F]
#
# Present in given but unused by this template (pass-through, executor ignores them):
#   Cgd      : float  — gate-drain capacitance [F]  (no Miller effect at drain in SF)
#   Cgs      : float  — gate-source capacitance [F]  (bootstrap effect neglected)
#   Rs_source: float  — signal source resistance [Ω] (input pole skipped, Rs_source=0)
#   gmb      : float  — body-effect transconductance [A/V] (body tied to source → 0)
#
# Note: kn = mun_Cox * (W/L) must be pre-computed by Module B before passing given.
# Note: VD = VDD (drain directly at supply); VD node omitted as trivially equal to VDD.
# ---------------------------------------------------------------------------

SF_RESISTOR_TEMPLATE: list[DAGNode] = [
    # Step 3: Q-point (large-signal DC analysis)
    # ID is solved first from the quadratic; VS, VGS, VOV, VDS follow in chain.
    DAGNode("ID",  3, "rule_sf_id_quadratic",       ["kn", "VG_DC", "Vth", "Rs_load"], "ID"),
    DAGNode("VS",  3, "rule_vs_from_id",             ["ID", "Rs_load"],                 "VS"),
    DAGNode("VGS", 3, "rule_vgs_nonzero_source",     ["VG_DC", "VS"],                   "VGS"),
    DAGNode("VOV", 3, "rule_overdrive_voltage",       ["VGS", "Vth"],                    "VOV"),
    DAGNode("VD",  3, "rule_vd_connected_to_supply", ["VDD"],                            "VD"),
    DAGNode("VDS", 3, "rule_vds_sf",                 ["VDD", "VS"],                     "VDS"),

    # Step 4: Q-point verification
    DAGNode("sat_check", 4, "rule_saturation_check", ["VDS", "VOV"],                    "sat_ok"),

    # Step 5: Small-signal parameter extraction
    DAGNode("gm",  5, "rule_transconductance",        ["kn", "VOV"],                    "gm"),
    DAGNode("ro",  5, "rule_output_resistance",       ["lambda", "ID"],                 "ro"),

    # Step 6: Low-frequency gain and output resistance
    # Req = Rs_load || ro (used for both Av and the first stage of Rout)
    # Rout = Req || (1/gm) via two chained calls to rule_parallel_resistance
    DAGNode("one_over_gm", 6, "rule_one_over_gm",    ["gm"],                           "one_over_gm"),
    DAGNode("Req",  6, "rule_parallel_resistance",    ["Rs_load", "ro"],                "Req"),
    DAGNode("Av",   6, "rule_sf_voltage_gain",        ["gm", "Req"],                    "Av"),
    DAGNode("Av_dB",6, "rule_av_to_db",               ["Av"],                           "Av_dB"),
    DAGNode("Rout", 6, "rule_parallel_resistance",    ["Req", "one_over_gm"],           "Rout"),

    # Step 7: High-frequency output capacitance (Cgs bootstrap effect neglected)
    DAGNode("Cout", 7, "rule_sf_output_capacitance",  ["CL"],                           "Cout"),

    # Step 8: Dominant pole at output node
    DAGNode("p1_omega", 8, "rule_rc_pole",            ["Rout", "Cout"],                 "p1_omega"),
    DAGNode("p1_Hz",    8, "rule_omega_to_hz",        ["p1_omega"],                     "p1_Hz"),
]


# ---------------------------------------------------------------------------
# Phase 2 — CS with ideal current source load (NMOS common-source, I_load to VDD)
#
# Q-point is reverse-solved: Iload forces ID directly; VDS_target is a design
# parameter. VOV, VGS, and VG_DC are back-calculated from the square law.
#
# Required given dict keys:
#   Iload      : float  — current source value [A]; forces ID = Iload
#   VDS_target : float  — design target drain-source voltage [V]
#   Vth        : float  — MOSFET threshold voltage [V]
#   kn         : float  — effective transconductance parameter mun_Cox*(W/L) [A/V²]
#   lambda     : float  — channel-length modulation coefficient [V⁻¹]; must be > 0
#                         (Rout = ro is finite and meaningful only when lambda > 0)
#   CL         : float  — explicit load capacitance [F]
#   Cgd        : float  — gate-drain overlap capacitance [F]
#
# Present in given but unused by this template:
#   VDD        : float  — supply voltage [V]
#   Cgs        : float  — gate-source capacitance [F]
#   Rs         : float  — signal source resistance [Ω] (Rs=0, input pole skipped)
#
# Note: kn = mun_Cox * (W/L) must be pre-computed by Module B.
# Note: VS = 0 throughout (CS grounded source); VD = VDS, VG_DC = VGS.
# ---------------------------------------------------------------------------

CS_IDEAL_CURRENT_SOURCE_TEMPLATE: list[DAGNode] = [
    # Step 3: Q-point (reverse solve: start from forced ID and target VDS)
    DAGNode("ID",    3, "rule_id_from_current_source",      ["Iload"],                    "ID"),
    DAGNode("VDS",   3, "rule_vds_from_target",             ["VDS_target"],               "VDS"),
    DAGNode("VOV",   3, "rule_vov_from_id_clm",             ["ID", "kn", "lambda", "VDS"],"VOV"),
    DAGNode("VGS",   3, "rule_vgs_from_vov",                ["VOV", "Vth"],               "VGS"),
    DAGNode("VG_DC", 3, "rule_vg_dc_grounded_source",       ["VGS"],                      "VG_DC"),
    DAGNode("VD",    3, "rule_vd_from_vds_grounded_source", ["VDS"],                      "VD"),

    # Step 4: Q-point verification
    DAGNode("sat_check", 4, "rule_saturation_check",        ["VDS", "VOV"],               "sat_ok"),

    # Step 5: Small-signal parameter extraction
    DAGNode("gm",    5, "rule_transconductance",             ["kn", "VOV"],               "gm"),
    DAGNode("ro",    5, "rule_output_resistance",            ["lambda", "ID"],            "ro"),

    # Step 6: Low-frequency gain and output resistance
    # Ideal current source load: small-signal resistance = ∞, so Rout = ro
    DAGNode("Rout",  6, "rule_rout_current_source_load",    ["ro"],                       "Rout"),
    DAGNode("Av",    6, "rule_cs_voltage_gain",             ["gm", "Rout"],               "Av"),
    DAGNode("Av_dB", 6, "rule_av_to_db",                   ["Av"],                       "Av_dB"),

    # Step 7: High-frequency output capacitance (Miller decomposition at drain)
    DAGNode("Cout",  7, "rule_miller_output_capacitance",   ["CL", "Cgd", "Av"],         "Cout"),

    # Step 8: Dominant pole at output node
    DAGNode("p1_omega", 8, "rule_rc_pole",                  ["Rout", "Cout"],            "p1_omega"),
    DAGNode("p1_Hz",    8, "rule_omega_to_hz",              ["p1_omega"],                "p1_Hz"),
]


# ---------------------------------------------------------------------------
# Phase 2 — CG with resistor drain load (NMOS common-gate, RD to VDD)
#
# Gate is held at fixed DC bias VG_bias; input signal enters at source.
# Q-point is a direct forward solve (no feedback, no quadratic) but
# VS = Vin_DC ≠ 0, so VGS and VDS both use two-node subtraction.
#
# Required given dict keys:
#   VDD      : float  — supply voltage [V]
#   VG_bias  : float  — DC gate bias voltage [V]
#   Vin_DC   : float  — source terminal DC voltage [V] (input signal DC level)
#   Vth      : float  — MOSFET threshold voltage [V]
#   kn       : float  — effective transconductance parameter mun_Cox*(W/L) [A/V²]
#   lambda   : float  — channel-length modulation coefficient [V⁻¹]; 0 to disable CLM
#   RD       : float  — drain resistor [Ω]
#   CL       : float  — explicit load capacitance [F]
#   Cgd      : float  — gate-drain overlap capacitance [F]
#
# Note: kn = mun_Cox * (W/L) must be pre-computed by Module B.
# Note: VS = Vin_DC throughout; Vin_DC is used directly wherever VS appears.
# ---------------------------------------------------------------------------

CG_RESISTOR_TEMPLATE: list[DAGNode] = [
    # Step 3: Q-point (direct forward solve — same structure as CS, but VS != 0)
    DAGNode("VGS",  3, "rule_vgs_cg",                   ["VG_bias", "Vin_DC"],       "VGS"),
    DAGNode("VOV",  3, "rule_overdrive_voltage",          ["VGS", "Vth"],              "VOV"),
    DAGNode("ID",   3, "rule_saturation_current_no_clm",  ["kn", "VOV"],               "ID"),
    DAGNode("VD",   3, "rule_kvl_drain_voltage",          ["VDD", "ID", "RD"],         "VD"),
    DAGNode("VDS",  3, "rule_vds_nonzero_source",         ["VD", "Vin_DC"],            "VDS"),

    # Step 4: Q-point verification
    DAGNode("sat_check", 4, "rule_saturation_check",     ["VDS", "VOV"],              "sat_ok"),

    # Step 5: Small-signal parameter extraction
    DAGNode("gm",   5, "rule_transconductance",           ["kn", "VOV"],               "gm"),
    DAGNode("ro",   5, "rule_output_resistance",          ["lambda", "ID"],            "ro"),

    # Step 6: Low-frequency gain, output resistance, and input resistance
    DAGNode("Rout", 6, "rule_parallel_resistance",        ["RD", "ro"],                "Rout"),
    DAGNode("Av",   6, "rule_cg_voltage_gain",            ["gm", "Rout"],              "Av"),
    DAGNode("Av_dB",6, "rule_av_to_db",                   ["Av"],                      "Av_dB"),
    DAGNode("Rin",  6, "rule_rin_cg",                     ["gm"],                      "Rin"),

    # Step 7: High-frequency output capacitance (Miller decomposition at drain node)
    DAGNode("Cout", 7, "rule_miller_output_capacitance",  ["CL", "Cgd", "Av"],        "Cout"),

    # Step 8: Dominant pole at output node
    DAGNode("p1_omega", 8, "rule_rc_pole",                ["Rout", "Cout"],           "p1_omega"),
    DAGNode("p1_Hz",    8, "rule_omega_to_hz",            ["p1_omega"],               "p1_Hz"),
]


# ---------------------------------------------------------------------------
# Phase 2 — Cascode with resistor drain load (M1=CS + M2=CG stacked)
#
# M1 (bottom): NMOS CS stage — input at M1.gate, M1.source = GND.
# M2 (top):    NMOS CG stage — M2.gate = VG2_bias (fixed), M2.drain = output.
# Intermediate node vx = M1.drain = M2.source.
#
# Q-point solve order:
#   M1 sets ID directly (CS square law).
#   M2 VOV2 is reverse-solved from ID (lambda=0 approximation, ADR-003).
#   vx is then derived from VG2_bias and VGS2.
#
# Required given dict keys:
#   VDD      : float  — supply voltage [V]
#   Vin_DC   : float  — M1 gate DC bias [V] (= VGS1 since M1.source = GND)
#   VG2_bias : float  — M2 gate fixed DC bias [V]
#   Vth1     : float  — M1 threshold voltage [V]
#   Vth2     : float  — M2 threshold voltage [V]
#   kn1      : float  — M1 mun_Cox*(W/L) [A/V²]
#   kn2      : float  — M2 mun_Cox*(W/L) [A/V²]
#   lambda1  : float  — M1 CLM coefficient [V⁻¹]
#   lambda2  : float  — M2 CLM coefficient [V⁻¹]
#   RD       : float  — drain resistor [Ω]
#   CL       : float  — explicit load capacitance [F] (at M2.drain = vo)
#   Cgd      : float  — M2 gate-drain capacitance [F] (Miller at output node)
#
# Note: kn1, kn2 = mun_Cox*(W/L) pre-computed by Module B for each device.
# Note: M2.body tied to GND (body effect disabled, gmb=0 for Phase 2).
# ---------------------------------------------------------------------------

CASCODE_RESISTOR_TEMPLATE: list[DAGNode] = [
    # Step 3: Q-point
    # M1 (CS): direct forward solve from M1.gate bias
    DAGNode("VGS1", 3, "rule_vgs_grounded_source",         ["Vin_DC"],               "VGS1"),
    DAGNode("VOV1", 3, "rule_overdrive_voltage",            ["VGS1", "Vth1"],         "VOV1"),
    DAGNode("ID",   3, "rule_saturation_current_no_clm",    ["kn1", "VOV1"],          "ID"),
    # M2 (CG): reverse-solve VOV2 from ID (VDS2 unknown at this point)
    DAGNode("VOV2", 3, "rule_vov_from_id_no_clm",           ["ID", "kn2"],            "VOV2"),
    DAGNode("VGS2", 3, "rule_vgs_from_vov",                 ["VOV2", "Vth2"],         "VGS2"),
    # Node voltages
    DAGNode("vx",   3, "rule_source_voltage_from_gate_vgs", ["VG2_bias", "VGS2"],     "vx"),
    DAGNode("vo",   3, "rule_kvl_drain_voltage",            ["VDD", "ID", "RD"],      "vo"),
    DAGNode("VDS1", 3, "rule_vds_grounded_source",          ["vx"],                   "VDS1"),
    DAGNode("VDS2", 3, "rule_vds_nonzero_source",           ["vo", "vx"],             "VDS2"),

    # Step 4: Q-point verification (both devices)
    DAGNode("sat_ok1", 4, "rule_saturation_check",          ["VDS1", "VOV1"],         "sat_ok1"),
    DAGNode("sat_ok2", 4, "rule_saturation_check",          ["VDS2", "VOV2"],         "sat_ok2"),

    # Step 5: Small-signal parameters (both devices; same ID flows through both)
    DAGNode("gm1",  5, "rule_transconductance",              ["kn1", "VOV1"],         "gm1"),
    DAGNode("ro1",  5, "rule_output_resistance",             ["lambda1", "ID"],       "ro1"),
    DAGNode("gm2",  5, "rule_transconductance",              ["kn2", "VOV2"],         "gm2"),
    DAGNode("ro2",  5, "rule_output_resistance",             ["lambda2", "ID"],       "ro2"),

    # Step 6: Low-frequency gain and output resistance
    # Cascode boosts Rout by (1 + gm2*ro1); then parallel with RD
    DAGNode("Rout_cascode", 6, "rule_cascode_output_resistance", ["gm2", "ro1", "ro2"], "Rout_cascode"),
    DAGNode("Rout", 6, "rule_parallel_resistance",           ["RD", "Rout_cascode"],  "Rout"),
    DAGNode("Av",   6, "rule_cs_voltage_gain",               ["gm1", "Rout"],         "Av"),
    DAGNode("Av_dB",6, "rule_av_to_db",                      ["Av"],                  "Av_dB"),

    # Step 7: High-frequency output capacitance (Miller decomposition at M2.drain)
    DAGNode("Cout", 7, "rule_miller_output_capacitance",     ["CL", "Cgd", "Av"],    "Cout"),

    # Step 8: Dominant pole at output node
    DAGNode("p1_omega", 8, "rule_rc_pole",                   ["Rout", "Cout"],       "p1_omega"),
    DAGNode("p1_Hz",    8, "rule_omega_to_hz",               ["p1_omega"],           "p1_Hz"),
]
