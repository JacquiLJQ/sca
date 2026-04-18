# Design Notes

---

## 1. Overall Pipeline Architecture

The pipeline has four modules. Each module's output is the next module's input.

```
Module A              Module B              Module C              Module D
Topology Generator -> Problem Setter     -> Solver            -> Packager
src/topology/         src/problem/          src/solver/           src/packager/

circuit.json          problem.json          solution.json         dataset/
circuit.cir           problem.md            solution.md           (deduplicated
                                            traces.jsonl           .jsonl or
                                            validation.log         .parquet)
```

**Module A — Topology Generator**
Produces a random but structurally valid CMOS amplifier circuit.
- Input: configuration parameters (allowed stage types, number of stages, parameter ranges).
- Output: `circuit.json` (incidence matrix + device metadata + node metadata) and `circuit.cir` (SPICE netlist derived from the incidence matrix).
- Must run a DC feasibility check via ngspice before passing the circuit downstream.
- If DC check fails, the circuit is discarded; Module A retries.

**Module B — Problem Setter**
Decides what question to ask about a given circuit.
- Input: `circuit.json` from Module A (already DC-verified).
- Output: `problem.json` (machine-readable: given parameters + question type + expected answer keys) and `problem.md` (human-readable question text).
- Question types: Q-point, low-frequency gain/Rin/Rout, dominant pole, bandwidth, a specific node voltage, etc.
- In Phase 1, only Q-point and low-frequency gain questions are generated.

### Canonical question types (Phase 1)

| question_type | asked_quantities | notes |
|---|---|---|
| qpoint | VGS_\<dev\>, VDS_\<dev\>, ID_\<dev\>, region_\<dev\> | per-device Q-point |
| low_freq_gain | Av, Av_dB, sign | low-frequency voltage gain only |
| input_resistance | Rin | midband Rin |
| output_resistance | Rout | midband Rout |

Phase 2+ adds: `dominant_pole`, `bandwidth_3dB`, `ugf`, `phase_margin`, etc.

**Module C — Solver**
Executes the 8-step skill.md procedure and produces a complete answer with a structured reasoning trace.
- Input: `circuit.json` + `problem.json`.
- Output: `solution.md` (template.md filled in full), `solution.json` (machine-readable structured answer), `traces.jsonl` (one JSON object per step), `validation.log` (SPICE vs. symbolic comparison).
- All numerical values are cross-validated against ngspice. Samples that fail the 1% tolerance check are discarded.

**Module D — Packager**
Aggregates raw samples into a clean dataset.
- Input: all validated `data/raw/<sample_id>/` directories.
- Output: a deduplicated dataset in `data/dataset/` (`.jsonl` or `.parquet`).
- Deduplication is based on circuit topology hash + question type. Near-duplicate circuits with different parameter values are kept.

---

## 2. Stage Port Data Structure

### Port Model (pydantic v2)

```python
from typing import Literal, Optional
from pydantic import BaseModel, Field


class Port(BaseModel):
    name: str                   # e.g. "in", "out", "cascode_bias"
    type: Literal["signal_in", "signal_out", "bias_in", "bias_out", "supply"]
    terminal: Literal["G", "D", "S", "B"]  # MOSFET terminal this port connects to
    polarity: Literal["inverting", "non_inverting", "differential"]
    impedance_level: Literal["high", "mid", "low"]
    dc_level: Literal["near_vdd", "mid", "near_gnd", "flexible"]
    differential_partner: Optional[str] = None  # name of the paired port, for diff signals
    internal_devices: list[str] = Field(default_factory=list)  # device ids this port directly connects to
```

> **Design decision**: `terminal` models only MOSFET terminals (`"G" | "D" | "S" | "B"`).
> Supply rails (VDD, VSS, GND) are not ports; they are attributes of nodes in `node_metadata`
> (e.g., `node_metadata["VDD"]["role"] = "supply_positive"`). Ports describe device terminals;
> supply connectivity is a node-level property.

> **`signal_out` vs `bias_out`**:
> - `signal_out`: propagates small-signal voltage/current to the next stage's `signal_in`.
> - `bias_out`: propagates DC bias (current or voltage) to the next stage's `bias_in`. Used by
>   current mirrors, bandgap references, and other bias generators.

### Standard Port Tables

#### CS — Common Source (NMOS, resistor load)

| name | type | terminal | polarity | impedance_level | dc_level | differential_partner |
|---|---|---|---|---|---|---|
| in | signal_in | G | non_inverting | high | flexible | None |
| out | signal_out | D | inverting | high | mid | None |

> Supply connections (VDD via RD, GND at source) are tracked in node_metadata, not as ports.

#### SF — Source Follower (NMOS)

| name | type | terminal | polarity | impedance_level | dc_level | differential_partner |
|---|---|---|---|---|---|---|
| in | signal_in | G | non_inverting | high | flexible | None |
| out | signal_out | S | non_inverting | low | mid | None |
| bias | bias_in | D | non_inverting | mid | near_vdd | None |

> **Design decision**: The `bias` port is at terminal D. It signals that this terminal requires
> a biasing primitive — a current source, resistor, or regulated supply — to be attached by the
> grammar. VDD-connected drains are a degenerate case where the grammar wires `bias` directly to
> a supply node in `node_metadata`. Current sources and current mirrors are reusable primitives
> in the stage library and are attached via composition, not hard-coded inside the SF stage.

#### CG — Common Gate (NMOS)

| name | type | terminal | polarity | impedance_level | dc_level | differential_partner |
|---|---|---|---|---|---|---|
| in | signal_in | S | non_inverting | low | flexible | None |
| out | signal_out | D | non_inverting | high | near_vdd | None |
| gate_bias | bias_in | G | non_inverting | high | mid | None |

#### Cascode (NMOS stacked: M1 CS + M2 CG)

| name | type | terminal | polarity | impedance_level | dc_level | differential_partner |
|---|---|---|---|---|---|---|
| in | signal_in | G (M1) | non_inverting | high | flexible | None |
| out | signal_out | D (M2) | inverting | high | near_vdd | None |
| cascode_bias | bias_in | G (M2) | non_inverting | high | mid | None |

> **Design decision**: Cascode is a composite stage in the library — sampled as one token
> during generation with three external ports (in, out, cascode_bias). Its internal structure
> (two MOSFETs: M_bot as CS driver, M_top as CG stack, with M_bot.D connected to M_top.S)
> is stored explicitly in `device_metadata`, not treated as a black box. Atomic CS and CG
> stages remain in the library for direct use. Phase 4 can unfold the internal metadata to
> derive folded cascode and gain-boosting variants without changing the port interface.

#### DiffPair (NMOS tail-biased, differential output)

| name | type | terminal | polarity | impedance_level | dc_level | differential_partner |
|---|---|---|---|---|---|---|
| in_p | signal_in | G (M1) | non_inverting | high | flexible | in_n |
| in_n | signal_in | G (M2) | differential | high | flexible | in_p |
| out_p | signal_out | D (M2) | non_inverting | high | mid | out_n |
| out_n | signal_out | D (M1) | inverting | high | mid | out_p |
| tail_bias | bias_in | S | non_inverting | mid | near_gnd | None |

> Polarity reasoning: when `in_p` rises, M1 current increases and M2 current decreases (tail
> current is shared). Therefore M1.D (= `out_n`) falls (inverting) and M2.D (= `out_p`) rises
> (non-inverting). Both output ports are always defined.
> `tail_bias` uses `terminal = "S"` (the dominant terminal type); its `internal_devices = ["M1", "M2"]`
> because the tail node connects to both sources. For single-transistor ports, `internal_devices`
> defaults to the primary device id (e.g., `["M1"]` for CS).
> **Design decision**: Phase 1 complexity is controlled by grammar rules (e.g., DiffPair must
> be followed by a CurrentMirrorLoad that merges `out_p` / `out_n` into a single-ended output),
> not by truncating the port definition. Differential behavior is a fundamental property of the
> stage, not a phase-specific simplification.

---

## 3. Incidence Matrix Specification

### Format Rules

- **Rows** = circuit nodes. Must include `VDD`, `GND`, and every internal node.
- **Columns** = device terminals (not devices). Every terminal of every device gets its own column.
  - MOSFET with id `M1`: columns `M1.D`, `M1.G`, `M1.S`, `M1.B`
  - Resistor with id `RD`: columns `RD.a`, `RD.b`
  - Capacitor with id `CL`: columns `CL.a`, `CL.b`
- **Entry value**: `1` if the terminal (column) connects to the node (row), `0` otherwise.
- **Constraint**: each column has exactly one `1` (every terminal connects to exactly one node).
- Node and column ordering is arbitrary but must be consistent within a sample.

### Storage Conventions

- In-memory type: `numpy.ndarray` with `dtype=np.int8`
- JSON serialization: `list[list[int]]`
- Sparse representation (`scipy.sparse.csr_matrix`) is used only when node count > 50
- Current Phase 1 circuits are all small; dense is default

### Example: NMOS CS Stage with Resistor Load

Circuit: M1 (NMOS), RD between VDD and M1.D. M1.S and M1.B tied to GND. M1.G = input node `vin`.

Nodes: `VDD`, `vo` (= M1.D = RD.b), `vin` (= M1.G), `GND`

|       | M1.D | M1.G | M1.S | M1.B | RD.a | RD.b |
|-------|:----:|:----:|:----:|:----:|:----:|:----:|
| VDD   |  0   |  0   |  0   |  0   |  1   |  0   |
| vo    |  1   |  0   |  0   |  0   |  0   |  1   |
| vin   |  0   |  1   |  0   |  0   |  0   |  0   |
| GND   |  0   |  0   |  1   |  1   |  0   |  0   |

Each column has exactly one `1`. The SPICE netlist and all graph representations are derived from this matrix — never the reverse.

### Metadata Attached to the Incidence Matrix

**`device_metadata`** — keyed by device id:

```json
{
  "M1": {
    "type": "NMOS",
    "W": 2e-6,
    "L": 180e-9,
    "model": "nmos_lvt",
    "match_group_id": null
  },
  "RD": {
    "type": "resistor",
    "value": 10000.0
  }
}
```

**`node_metadata`** — keyed by node id:

```json
{
  "VDD": { "role": "supply",  "voltage_dc": 1.8  },
  "GND": { "role": "ground",  "voltage_dc": 0.0  },
  "vo":  { "role": "output",  "voltage_dc": null  },
  "vin": { "role": "input",   "voltage_dc": null  }
}
```

`voltage_dc: null` means the value must be solved by DC analysis; it is filled in after Module C runs.

---

## 4. Grammar Rules (Topology Composition)

Grammar rules govern which stage-to-stage connections are structurally valid. The full grammar is defined later (Phase 2+). Here we specify the rule hierarchy.

### Layer 1 — Hard Constraints (always enforced)

1. **Port type must match**: a `signal_out` port may only connect to a `signal_in` port; a `bias_in` port may only connect to a `bias_out` or `supply` port. Cross-type connections are illegal.
2. **Differential signals must be routed in pairs**: if `in_p` of a downstream stage is connected, `in_n` must also be connected, and the `differential_partner` fields must cross-reference each other.
3. **No direct VDD–GND short**: no composition step may create a path with zero resistance between supply rails.
4. **DC level compatibility**: a `near_vdd` output port must not connect to a `near_gnd` input port without an intervening level-shifting stage.
5. **No floating inputs**: every `signal_in` and `bias_in` port of an instantiated stage must be driven.

### Layer 2 — Soft Preferences (weighted, used by Module A sampler)

| pattern | description | default weight |
|---|---|---:|
| CS → SF | voltage amplifier followed by source-follower buffer | 0.30 |
| DiffPair → CurrentMirrorLoad | differential pair with active current-mirror load | 0.25 |
| CS → Cascode | gain boosting by stacking a CG on top of CS | 0.20 |
| DiffPair → CS | differential input stage followed by single-ended CS gain stage | 0.15 |
| CS → CS | two-stage inverting amplifier | 0.10 |

Weights are used as unnormalized sampling probabilities when Module A randomly selects a composition pattern. They can be overridden in config.

**Phase 1 note**: only the atomic CS stage is instantiated directly (no composition). The patterns above activate from Phase 2 onward when SF / CG / Cascode / DiffPair are added.

---

## 5. Ground Truth Strategy

### Why ngspice is the ground truth

Closed-form hand analysis involves approximations (region assumptions, ignoring body effect, simplifying loads). ngspice solves the full nonlinear DC equations and the linearized AC equations numerically without these simplifications. Any discrepancy between hand analysis and simulation points to an error in the reasoning trace, not in the simulator.

### Numerical answer policy

- All reported numerical answers (node voltages, branch currents, gain, bandwidth, poles) use the ngspice result as the authoritative value.
- ngspice is invoked via `subprocess` (calling the `ngspice` binary directly) or via `PySpice`. The solver must not re-implement SPICE numerics.
- DC operating point: use ngspice `.op` analysis.
- AC frequency response: use ngspice `.ac` analysis.
- Pole-zero: use ngspice `.pz` analysis where available; otherwise derive from `.ac` data.

### Symbolic expression policy

- SymPy is used to derive symbolic expressions (e.g., `Av = -gm * (RD || ro)`).
- After symbolic derivation, substitute all given numerical parameters and evaluate.
- Compare the symbolic numerical result against the ngspice result. Tolerance: ≤ 1% relative error.
- If the tolerance is exceeded, the sample is discarded. The reason is logged in `validation.log` with both values.

### Approximation policy

- Symbolic derivations may apply standard approximations from skill.md Section 7 (Miller, OCTC, TTC). Each applied approximation must be named explicitly in the trace entry's `actions` field.
- Numerical evaluation compares against ngspice (which applies no approximations). The 1% tolerance absorbs approximation error; samples where approximations introduce > 1% error are discarded, not adjusted.
- When a derivation drops a term, the `derivations` field must note it explicitly (example: `"C_out ≈ CL, neglecting Cgd(1−1/Av) by Miller approximation"`).

### Discard and retry

When a sample is discarded (DC infeasible, tolerance exceeded, or incomplete template), Module A generates a new circuit. Discard events are logged with full context for later analysis.

### Failure modes and retry policy

- **ngspice process crash or timeout (> 30 s)**: log the error, discard the circuit, retry Module A.
- **DC non-convergence (`.op` fails)**: log convergence diagnostics to `validation.log`, discard the sample.
- **Simulation warnings** (node voltage outside rails, device out of model range): logged to `validation.log` but not treated as fatal; the sample proceeds unless a hard constraint is also violated.
- **Max retries per circuit generation in Module A**: 5. If all 5 attempts fail, log the failure and move on; the failed parameter set is saved for post-mortem analysis.

---

## 6. Reasoning Trace Format

Each trace is a JSONL file (`traces.jsonl`) where each line is one step from skill.md.

### Schema for one trace entry

```json
{
  "step_number": 1,
  "step_name": "recognize_topology",
  "inputs": [],
  "actions": [
    "Identified NMOS M1 as the input transistor",
    "Identified RD as the load element converting drain current to output voltage",
    "Noted vo (drain of M1) as the high-impedance output node"
  ],
  "derivations": [],
  "outputs": {
    "topology": "common_source",
    "input_node": "vin",
    "output_node": "vo",
    "high_impedance_nodes": ["vo"],
    "expected_gain_polarity": "inverting"
  },
  "justification": "skill.md Step 1: Recognize the topology"
}
```

Field definitions:

| field | type | description |
|---|---|---|
| `step_number` | int (1–8) | position in the skill.md workflow |
| `step_name` | str | snake_case name matching the skill.md step |
| `inputs` | list[str] | output keys from prior steps referenced by this step |
| `actions` | list[str] | natural language description of operations performed |
| `derivations` | list[str] | key equations or derivation steps; use LaTeX strings |
| `outputs` | dict | results produced by this step (free schema, step-dependent) |
| `justification` | str | citation of the skill.md section that mandates this step |

### Step names (canonical)

| step_number | step_name |
|---|---|
| 1 | `recognize_topology` |
| 2 | `dc_reduction` |
| 3 | `qpoint_solve` |
| 4 | `qpoint_verify` |
| 5 | `small_signal_extraction` |
| 6 | `low_frequency_analysis` |
| 7 | `high_frequency_analysis` |
| 8 | `pole_zero_analysis` |

### Complete 8-step example (NMOS CS, RD=10kΩ, VDD=1.8V, VG=0.9V, kn=1mA/V², VTH=0.5V, λ=0, Cgs=20fF, Cgd=5fF, CL=100fF)

```jsonl
{"step_number": 1, "step_name": "recognize_topology", "inputs": [], "actions": ["M1 is NMOS with gate at vin, drain at vo, source at GND", "RD connects VDD to vo", "Stage is common-source: input at G, output at D"], "derivations": [], "outputs": {"topology": "common_source", "input_node": "vin", "output_node": "vo", "load": "RD", "expected_gain_polarity": "inverting"}, "justification": "skill.md Step 1"}
{"step_number": 2, "step_name": "dc_reduction", "inputs": [], "actions": ["Set AC input vin_ac = 0", "Open all capacitors (Cgs, Cgd, CL)"], "derivations": [], "outputs": {"dc_circuit_notes": "vin = VG_DC = 0.9V, only M1 and RD remain active"}, "justification": "skill.md Step 2"}
{"step_number": 3, "step_name": "qpoint_solve", "inputs": ["step_2.outputs"], "actions": ["Assume M1 in saturation", "Write ID = (1/2) kn (VGS - VTH)^2", "Compute VD = VDD - ID * RD"], "derivations": ["V_{GS} = V_G - V_S = 0.9 - 0 = 0.9\\,\\text{V}", "I_D = \\frac{1}{2}(10^{-3})(0.9-0.5)^2 = 80\\,\\mu\\text{A}", "V_D = 1.8 - (80\\times10^{-6})(10^4) = 1.0\\,\\text{V}"], "outputs": {"VGS": 0.9, "VDS": 1.0, "ID_uA": 80, "VD": 1.0, "VS": 0.0}, "justification": "skill.md Step 3"}
{"step_number": 4, "step_name": "qpoint_verify", "inputs": ["step_3.outputs"], "actions": ["Check VDS >= VGS - VTH for saturation", "Check node voltages within rails", "Check ID is physically reasonable"], "derivations": ["V_{DS} = 1.0\\,\\text{V} \\geq V_{GS} - V_{TH} = 0.4\\,\\text{V} \\quad \\checkmark"], "outputs": {"assumed_region": "saturation", "verified_region": "saturation", "qpoint_valid": true}, "justification": "skill.md Step 4"}
{"step_number": 5, "step_name": "small_signal_extraction", "inputs": ["step_3.outputs", "step_4.outputs"], "actions": ["Compute gm from Q-point", "ro = infinity because lambda = 0"], "derivations": ["g_m = \\frac{2I_D}{V_{OV}} = \\frac{2(80\\times10^{-6})}{0.4} = 0.4\\,\\text{mA/V}", "r_o = \\frac{1}{\\lambda I_D} \\to \\infty"], "outputs": {"gm_mA_per_V": 0.4, "ro": null, "ro_note": "infinite: lambda=0", "VOV": 0.4}, "justification": "skill.md Step 5"}
{"step_number": 6, "step_name": "low_frequency_analysis", "inputs": ["step_5.outputs"], "actions": ["Ignore all capacitors", "Output node: vo driven by gm*vgs, loaded by RD and ro in parallel", "Rin = infinity (gate terminal)", "Rout = RD || ro"], "derivations": ["A_v = -g_m (R_D \\| r_o) = -0.4\\times10^{-3} \\times 10^4 = -4", "R_{in} = \\infty", "R_{out} = R_D = 10\\,\\text{k}\\Omega"], "outputs": {"Av": -4.0, "Av_dB": -12.04, "Rin": null, "Rin_note": "infinite: MOSFET gate draws no DC current", "Rout_ohm": 10000, "sign": "inverting"}, "justification": "skill.md Step 6"}
{"step_number": 7, "step_name": "high_frequency_analysis", "inputs": ["step_5.outputs", "step_6.outputs"], "actions": ["Add Cgs, Cgd, CL to small-signal model", "Apply Miller approximation to Cgd", "Identify high-impedance nodes: vin (with Miller cap), vo (with CL)"], "derivations": ["C_{gd,Miller,in} = C_{gd}(1 - A_v) = 5\\,\\text{fF} \\times 5 = 25\\,\\text{fF}", "C_{in,total} = C_{gs} + C_{gd,Miller} = 20 + 25 = 45\\,\\text{fF}", "C_{out,total} = C_L + C_{gd}(1 - 1/A_v) \\approx C_L = 100\\,\\text{fF}"], "outputs": {"C_in_total_fF": 45, "C_out_total_fF": 100, "Miller_applied": true}, "justification": "skill.md Step 7"}
{"step_number": 8, "step_name": "pole_zero_analysis", "inputs": ["step_5.outputs", "step_6.outputs", "step_7.outputs"], "actions": ["Dominant pole at output node vo: p1 = 1 / (Rout * C_out)", "Non-dominant pole at input: p2 = 1 / (Rs * C_in) — Rs = source impedance, set to 50 ohm for estimate", "No RHP zero because lambda=0 and simple topology"], "derivations": ["p_1 = \\frac{1}{R_{out} C_{out}} = \\frac{1}{10^4 \\times 10^{-13}} = 10^9\\,\\text{rad/s} \\approx 159\\,\\text{MHz}", "p_2 = \\frac{1}{R_s C_{in}} = \\frac{1}{50 \\times 45\\times10^{-15}} \\approx 444\\,\\text{GHz} \\quad (\\text{non-dominant})"], "outputs": {"p1_rad_per_s": 1e9, "p1_Hz": 1.59e8, "p2_Hz": 4.44e11, "dominant_pole": "p1", "zeros": [], "bandwidth_Hz": 1.59e8}, "justification": "skill.md Step 8"}
```

### Numerical representation conventions

- **Finite numbers**: JSON number (`int` or `float`).
- **Infinite / undefined** (e.g., `ro` when `lambda=0`): use `null`, and add a sibling `_note` field explaining why.
  ```json
  "ro": null,
  "ro_note": "infinite: channel-length modulation not included (lambda=0)"
  ```
- **Unsolved fields**: `null` (not the string `"not solved"`).
- **Markdown reports** (`solution.md`) may use `"not provided"` / `"not derived"` for human readability, but JSON (`solution.json`, `traces.jsonl`) always uses `null`.

---

## 7. File Layout for One Sample

Each sample is stored under `data/raw/<sample_id>/` where `sample_id` is a UUID or a deterministic hash.

```
data/raw/<sample_id>/
├── circuit.json        # incidence matrix + device_metadata + node_metadata
├── circuit.cir         # SPICE netlist (derived from circuit.json, do not edit manually)
├── problem.md          # human-readable question
├── problem.json        # machine-readable: given_parameters + question_type + expected_keys
├── solution.md         # template.md filled in full (all 10 sections)
├── solution.json       # machine-readable structured answer (mirrors solution.md fields)
├── traces.jsonl        # 8 reasoning steps, one JSON object per line
└── validation.log      # SPICE vs. symbolic comparison record
```

### `circuit.json` top-level structure

```json
{
  "sample_id": "<uuid>",
  "incidence_matrix": { "nodes": [...], "terminals": [...], "matrix": [[...]] },
  "device_metadata": { "<device_id>": { ... } },
  "node_metadata": { "<node_id>": { ... } }
}
```

### `problem.json` top-level structure

```json
{
  "sample_id": "<uuid>",
  "question_type": "qpoint | low_freq_gain | input_resistance | output_resistance",
  "given_parameters": { "<param_name>": <value>, ... },
  "asked_quantities": ["ID_M1", "VD_M1", "Av"],
  "question_text_ref": "problem.md"
}
```

### `solution.json` top-level structure

```json
{
  "sample_id": "<uuid>",
  "qpoint": { "M1": { "VGS": 0.9, "VDS": 1.0, "ID_uA": 80, "region": "saturation" } },
  "small_signal": { "M1": { "gm_mA_per_V": 0.4, "ro": null, "ro_note": "infinite: lambda=0" } },
  "low_frequency": { "Av": -4.0, "Rin": null, "Rin_note": "infinite: MOSFET gate", "Rout_ohm": 10000 },
  "high_frequency": { "dominant_pole_Hz": 1.59e8, "bandwidth_Hz": 1.59e8 },
  "spice_reference": { "Av_spice": -3.98, "dominant_pole_Hz_spice": 1.61e8 },
  "validation_passed": true
}
```

### `validation.log` format (plain text)

```
sample_id: <uuid>
timestamp: 2026-04-18T00:00:00Z
quantity       symbolic       spice          rel_error      pass
Av             -4.000         -3.980         0.50%          YES
dominant_pole  1.590e+08      1.610e+08      1.24%          NO   <- DISCARD
```

If any quantity fails, the entire sample is discarded and this file is moved to `data/raw/<sample_id>/DISCARDED/validation.log` for post-mortem analysis.
