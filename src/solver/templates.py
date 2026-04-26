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
