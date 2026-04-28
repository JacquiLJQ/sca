"""Level 2 stage library: reusable StageSpec building blocks (ADR-007 D2).

Signal stages (have input → output signal path):
  CS_CORE           — NMOS common-source, forward Q-point solve
  CS_CORE_ICS       — NMOS common-source, reverse Q-point solve (for ICS load)
  SF_CORE           — NMOS source follower, standalone (source resistor integrated)
  CG_CORE           — NMOS common-gate

Load / bias blocks (provide load resistance, no signal path):
  RESISTOR_LOAD     — drain resistor RD from VDD to drain node
  CURRENT_SOURCE_LOAD — ideal current source from VDD to drain node

Port connection conventions:
  Signal stage "vout" port connects to load "load_bot" port.
  Supply/ground ports are merged globally by the compositor.
"""

from src.topology.models import IncidenceMatrix
from src.topology.stage_spec import DeviceSpec, MicroDagEntry, PortSpec, StageSpec


# ---------------------------------------------------------------------------
# CS_CORE  — NMOS common-source, forward Q-point solve
# local nodes: gate, drain, gnd
# ---------------------------------------------------------------------------

CS_CORE = StageSpec(
    stage_type="cs_core",
    category="signal",
    ports={
        "vin":  PortSpec("vin",  "input",  "voltage", "high", "gate",  "gate",  dc_from_given="VG_DC"),
        "vout": PortSpec("vout", "output", "voltage", "high", "drain", "drain"),
        "gnd":  PortSpec("gnd",  "ground", "voltage", "low",  "gnd",   "gnd"),
    },
    devices=[
        DeviceSpec("M1", "nmos", ["D", "G", "S", "B"], ["W", "L"]),
    ],
    local_nodes=["gate", "drain", "gnd"],
    local_incidence=IncidenceMatrix(
        nodes=["gate", "drain", "gnd"],
        terminals=["M1.D", "M1.G", "M1.S", "M1.B"],
        matrix=[
            [0, 1, 0, 0],  # gate  — M1.G
            [1, 0, 0, 0],  # drain — M1.D
            [0, 0, 1, 1],  # gnd   — M1.S, M1.B
        ],
    ),
    qpoint_entries=[
        MicroDagEntry("VGS", 3, "rule_vgs_grounded_source",      ["VG_DC"],        "VGS"),
        MicroDagEntry("VOV", 3, "rule_overdrive_voltage",         ["VGS", "Vth"],   "VOV"),
        MicroDagEntry("ID",  3, "rule_saturation_current_no_clm", ["kn",  "VOV"],   "ID"),
    ],
    vds_entries=[
        MicroDagEntry("VDS", 3, "rule_vds_grounded_source", ["VD"], "VDS"),
    ],
    satcheck_entries=[
        MicroDagEntry("sat_check", 4, "rule_saturation_check", ["VDS", "VOV"], "sat_ok"),
    ],
    ss_entries=[
        MicroDagEntry("gm", 5, "rule_transconductance_clm", ["kn", "VOV", "lambda", "VDS"], "gm"),
        MicroDagEntry("ro", 5, "rule_output_resistance", ["lambda", "ID"],  "ro"),
    ],
    rout_entries=[],
    gain_entries=[
        MicroDagEntry("Av",    6, "rule_cs_voltage_gain", ["gm",  "Rout"], "Av"),
        MicroDagEntry("Av_dB", 6, "rule_av_to_db",        ["Av"],          "Av_dB"),
    ],
    hf_entries=[
        MicroDagEntry("Cout", 7, "rule_miller_output_capacitance", ["CL", "Cgd", "Av"], "Cout"),
    ],
    pole_entries=[
        MicroDagEntry("p1_omega", 8, "rule_rc_pole",      ["Rout", "Cout"],  "p1_omega"),
        MicroDagEntry("p1_Hz",    8, "rule_omega_to_hz",  ["p1_omega"],       "p1_Hz"),
    ],
    small_signal_summary_rule="rule_cs_voltage_gain",
)


# ---------------------------------------------------------------------------
# CS_CORE_ICS  — NMOS common-source, reverse Q-point solve (for ICS load)
# ID and VDS are given (Iload, VDS_target); VOV/VGS/VG_DC are back-calculated.
# local nodes: gate, drain, gnd  (same connectivity as CS_CORE)
# ---------------------------------------------------------------------------

CS_CORE_ICS = StageSpec(
    stage_type="cs_core_ics",
    category="signal",
    ports={
        "vin":  PortSpec("vin",  "input",  "voltage", "high", "gate",  "gate",  dc_from_given="VG_DC"),
        "vout": PortSpec("vout", "output", "voltage", "high", "drain", "drain"),
        "gnd":  PortSpec("gnd",  "ground", "voltage", "low",  "gnd",   "gnd"),
    },
    devices=[
        DeviceSpec("M1", "nmos", ["D", "G", "S", "B"], ["W", "L"]),
    ],
    local_nodes=["gate", "drain", "gnd"],
    local_incidence=IncidenceMatrix(
        nodes=["gate", "drain", "gnd"],
        terminals=["M1.D", "M1.G", "M1.S", "M1.B"],
        matrix=[
            [0, 1, 0, 0],
            [1, 0, 0, 0],
            [0, 0, 1, 1],
        ],
    ),
    qpoint_entries=[
        MicroDagEntry("ID",     3, "rule_id_from_current_source",      ["Iload"],                         "ID"),
        MicroDagEntry("VDS",    3, "rule_vds_from_target",             ["VDS_target"],                    "VDS"),
        MicroDagEntry("VOV",    3, "rule_vov_from_id_clm",             ["ID", "kn", "lambda", "VDS"],     "VOV"),
        MicroDagEntry("VGS",    3, "rule_vgs_from_vov",                ["VOV", "Vth"],                    "VGS"),
        MicroDagEntry("VG_DC",  3, "rule_vg_dc_grounded_source",       ["VGS"],                           "VG_DC"),
        MicroDagEntry("VD",     3, "rule_vd_from_vds_grounded_source", ["VDS"],                           "VD"),
    ],
    vds_entries=[],   # VDS already set in qpoint_entries
    satcheck_entries=[
        MicroDagEntry("sat_check", 4, "rule_saturation_check", ["VDS", "VOV"], "sat_ok"),
    ],
    ss_entries=[
        MicroDagEntry("gm", 5, "rule_transconductance_clm", ["kn", "VOV", "lambda", "VDS"], "gm"),
        MicroDagEntry("ro", 5, "rule_output_resistance", ["lambda", "ID"],  "ro"),
    ],
    rout_entries=[],
    gain_entries=[
        MicroDagEntry("Av",    6, "rule_cs_voltage_gain", ["gm",  "Rout"], "Av"),
        MicroDagEntry("Av_dB", 6, "rule_av_to_db",        ["Av"],          "Av_dB"),
    ],
    hf_entries=[
        MicroDagEntry("Cout", 7, "rule_miller_output_capacitance", ["CL", "Cgd", "Av"], "Cout"),
    ],
    pole_entries=[
        MicroDagEntry("p1_omega", 8, "rule_rc_pole",     ["Rout", "Cout"], "p1_omega"),
        MicroDagEntry("p1_Hz",    8, "rule_omega_to_hz", ["p1_omega"],     "p1_Hz"),
    ],
    small_signal_summary_rule="rule_cs_voltage_gain",
)


# ---------------------------------------------------------------------------
# SF_CORE  — NMOS source follower, standalone (source resistor integrated)
# local nodes: gate, vdd, source, gnd
# ---------------------------------------------------------------------------

SF_CORE = StageSpec(
    stage_type="sf_core",
    category="signal",
    ports={
        "vin":    PortSpec("vin",    "input",   "voltage", "high", "gate",   "gate",   dc_from_given="VG_DC"),
        "vout":   PortSpec("vout",   "output",  "voltage", "low",  "source", "source"),
        "supply": PortSpec("supply", "supply",  "voltage", "low",  "vdd",    "vdd",    dc_from_given="VDD"),
        "gnd":    PortSpec("gnd",    "ground",  "voltage", "low",  "gnd",    "gnd"),
    },
    devices=[
        DeviceSpec("M1", "nmos",     ["D", "G", "S", "B"], ["W", "L"]),
        DeviceSpec("Rs", "resistor", ["a", "b"],            ["Rs_load"]),
    ],
    local_nodes=["gate", "vdd", "source", "gnd"],
    local_incidence=IncidenceMatrix(
        nodes=["gate", "vdd", "source", "gnd"],
        terminals=["M1.D", "M1.G", "M1.S", "M1.B", "Rs.a", "Rs.b"],
        matrix=[
            [0, 1, 0, 0, 0, 0],  # gate   — M1.G
            [1, 0, 0, 0, 0, 0],  # vdd    — M1.D
            [0, 0, 1, 0, 1, 0],  # source — M1.S, Rs.a
            [0, 0, 0, 1, 0, 1],  # gnd    — M1.B, Rs.b
        ],
    ),
    qpoint_entries=[
        MicroDagEntry("ID",  3, "rule_sf_id_quadratic",      ["kn", "VG_DC", "Vth", "Rs_load"], "ID"),
        MicroDagEntry("VS",  3, "rule_vs_from_id",           ["ID",  "Rs_load"],                 "VS"),
        MicroDagEntry("VGS", 3, "rule_vgs_nonzero_source",   ["VG_DC", "VS"],                    "VGS"),
        MicroDagEntry("VOV", 3, "rule_overdrive_voltage",    ["VGS", "Vth"],                     "VOV"),
        MicroDagEntry("VD",  3, "rule_vd_connected_to_supply", ["VDD"],                          "VD"),
    ],
    vds_entries=[
        MicroDagEntry("VDS", 3, "rule_vds_sf", ["VDD", "VS"], "VDS"),
    ],
    satcheck_entries=[
        MicroDagEntry("sat_check", 4, "rule_saturation_check", ["VDS", "VOV"], "sat_ok"),
    ],
    ss_entries=[
        MicroDagEntry("gm", 5, "rule_transconductance_clm", ["kn", "VOV", "lambda", "VDS"], "gm"),
        MicroDagEntry("ro", 5, "rule_output_resistance", ["lambda", "ID"],  "ro"),
    ],
    rout_entries=[],
    gain_entries=[
        MicroDagEntry("one_over_gm", 6, "rule_one_over_gm",        ["gm"],                    "one_over_gm"),
        MicroDagEntry("Req",         6, "rule_parallel_resistance", ["Rs_load", "ro"],         "Req"),
        MicroDagEntry("Av",          6, "rule_sf_voltage_gain",     ["gm",      "Req"],        "Av"),
        MicroDagEntry("Av_dB",       6, "rule_av_to_db",            ["Av"],                    "Av_dB"),
        MicroDagEntry("Rout",        6, "rule_parallel_resistance", ["Req",     "one_over_gm"],"Rout"),
    ],
    hf_entries=[
        MicroDagEntry("Cout", 7, "rule_sf_output_capacitance", ["CL"], "Cout"),
    ],
    pole_entries=[
        MicroDagEntry("p1_omega", 8, "rule_rc_pole",     ["Rout", "Cout"], "p1_omega"),
        MicroDagEntry("p1_Hz",    8, "rule_omega_to_hz", ["p1_omega"],     "p1_Hz"),
    ],
    small_signal_summary_rule="rule_sf_voltage_gain",
)


# ---------------------------------------------------------------------------
# CG_CORE  — NMOS common-gate
# local nodes: vg_bias, drain, source, gnd
# ---------------------------------------------------------------------------

CG_CORE = StageSpec(
    stage_type="cg_core",
    category="signal",
    ports={
        "vin":      PortSpec("vin",      "input",  "voltage", "low",  "source",  "source",  dc_from_given="Vin_DC"),
        "vout":     PortSpec("vout",     "output", "voltage", "high", "drain",   "drain"),
        "vg_bias":  PortSpec("vg_bias",  "supply", "voltage", "low",  "vg_bias", "vg_bias", dc_from_given="VG_bias"),
        "gnd":      PortSpec("gnd",      "ground", "voltage", "low",  "gnd",     "gnd"),
    },
    devices=[
        DeviceSpec("M1", "nmos", ["D", "G", "S", "B"], ["W", "L"]),
    ],
    local_nodes=["vg_bias", "drain", "source", "gnd"],
    local_incidence=IncidenceMatrix(
        nodes=["vg_bias", "drain", "source", "gnd"],
        terminals=["M1.D", "M1.G", "M1.S", "M1.B"],
        matrix=[
            [0, 1, 0, 0],  # vg_bias — M1.G
            [1, 0, 0, 0],  # drain   — M1.D
            [0, 0, 1, 0],  # source  — M1.S
            [0, 0, 0, 1],  # gnd     — M1.B
        ],
    ),
    qpoint_entries=[
        MicroDagEntry("VGS", 3, "rule_vgs_cg",                   ["VG_bias", "Vin_DC"], "VGS"),
        MicroDagEntry("VOV", 3, "rule_overdrive_voltage",          ["VGS", "Vth"],        "VOV"),
        MicroDagEntry("ID",  3, "rule_saturation_current_no_clm", ["kn", "VOV"],         "ID"),
    ],
    vds_entries=[
        MicroDagEntry("VDS", 3, "rule_vds_nonzero_source", ["VD", "Vin_DC"], "VDS"),
    ],
    satcheck_entries=[
        MicroDagEntry("sat_check", 4, "rule_saturation_check", ["VDS", "VOV"], "sat_ok"),
    ],
    ss_entries=[
        MicroDagEntry("gm", 5, "rule_transconductance_clm", ["kn", "VOV", "lambda", "VDS"], "gm"),
        MicroDagEntry("ro", 5, "rule_output_resistance", ["lambda", "ID"],  "ro"),
    ],
    rout_entries=[],
    gain_entries=[
        MicroDagEntry("Av",    6, "rule_cg_voltage_gain", ["gm",  "Rout"], "Av"),
        MicroDagEntry("Av_dB", 6, "rule_av_to_db",        ["Av"],          "Av_dB"),
        MicroDagEntry("Rin",   6, "rule_rin_cg",          ["gm"],          "Rin"),
    ],
    hf_entries=[
        MicroDagEntry("Cout", 7, "rule_miller_output_capacitance", ["CL", "Cgd", "Av"], "Cout"),
    ],
    pole_entries=[
        MicroDagEntry("p1_omega", 8, "rule_rc_pole",     ["Rout", "Cout"], "p1_omega"),
        MicroDagEntry("p1_Hz",    8, "rule_omega_to_hz", ["p1_omega"],     "p1_Hz"),
    ],
    small_signal_summary_rule="rule_cg_voltage_gain",
)


# ---------------------------------------------------------------------------
# RESISTOR_LOAD  — drain resistor RD from VDD to drain top node
# local nodes: vdd, top
# ---------------------------------------------------------------------------

RESISTOR_LOAD = StageSpec(
    stage_type="resistor_load",
    category="load",
    ports={
        "supply":   PortSpec("supply",   "supply",   "voltage", "low", "vdd", "vdd", dc_from_given="VDD"),
        "load_bot": PortSpec("load_bot", "load_bot", "voltage", "high", "drain_load", "top"),
    },
    devices=[
        DeviceSpec("RD", "resistor", ["a", "b"], ["RD"]),
    ],
    local_nodes=["vdd", "top"],
    local_incidence=IncidenceMatrix(
        nodes=["vdd", "top"],
        terminals=["RD.a", "RD.b"],
        matrix=[
            [1, 0],  # vdd — RD.a
            [0, 1],  # top — RD.b
        ],
    ),
    qpoint_entries=[
        MicroDagEntry("VD", 3, "rule_kvl_drain_voltage", ["VDD", "ID", "RD"], "VD"),
    ],
    vds_entries=[],
    satcheck_entries=[],
    ss_entries=[],
    rout_entries=[
        MicroDagEntry("Rout", 6, "rule_parallel_resistance", ["RD", "ro"], "Rout"),
    ],
    gain_entries=[],
    hf_entries=[],
    pole_entries=[],
    small_signal_summary_rule="rule_parallel_resistance",
)


# ---------------------------------------------------------------------------
# CURRENT_SOURCE_LOAD  — ideal current source I1 from VDD to drain node
# local nodes: vdd, top
# ---------------------------------------------------------------------------

CURRENT_SOURCE_LOAD = StageSpec(
    stage_type="current_source_load",
    category="load",
    ports={
        "supply":   PortSpec("supply",   "supply",   "voltage", "low",  "vdd", "vdd", dc_from_given="VDD"),
        "load_bot": PortSpec("load_bot", "load_bot", "voltage", "high", "drain_load", "top"),
    },
    devices=[
        DeviceSpec("I1", "current_source", ["a", "b"], ["Iload"]),
    ],
    local_nodes=["vdd", "top"],
    local_incidence=IncidenceMatrix(
        nodes=["vdd", "top"],
        terminals=["I1.a", "I1.b"],
        matrix=[
            [1, 0],  # vdd — I1.a (N+)
            [0, 1],  # top — I1.b (N-)
        ],
    ),
    qpoint_entries=[],   # Q-point handled entirely by CS_CORE_ICS
    vds_entries=[],
    satcheck_entries=[],
    ss_entries=[],
    rout_entries=[
        MicroDagEntry("Rout", 6, "rule_rout_current_source_load", ["ro"], "Rout"),
    ],
    gain_entries=[],
    hf_entries=[],
    pole_entries=[],
    small_signal_summary_rule="rule_rout_current_source_load",
)
