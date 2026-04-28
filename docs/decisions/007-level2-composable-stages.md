# ADR 007: Level 2 — Composable Stage Architecture

## Status
Accepted, 2026-04-26.

## Context
Level 1 generates fixed single-stage topologies (CS+R, SF+R, CG+R, Cascode+R, 
CS+ICS). Each topology has a hand-written generator and a hand-written DAG 
template. This approach does not scale: adding a new topology requires writing 
both a generator and a template from scratch.

Level 2 enables LEGO-style composition: define reusable building blocks 
(stages), connect their ports, auto-merge incidence matrices, and 
auto-generate DAG templates. The combination space grows exponentially 
with the number of stages, producing genuine topological diversity.

## Decisions

### D1: StageSpec and PortSpec

Every composable building block is a StageSpec:

    @dataclass
    class PortSpec:
        name: str
        kind: str               # "input", "output", "bias", "supply", "ground", "load", "tail"
        signal_type: str        # "voltage", "current", "differential", "common_mode"
        impedance: str          # "high", "medium", "low"
        role: str               # "gate", "drain", "source", "tail", "load", etc.
        node_ref: str           # local node name inside the stage
        dc_voltage_range: tuple[float, float] | None = None  # acceptable DC voltage range

    @dataclass
    class StageSpec:
        stage_type: str                    # e.g., "cs_core", "resistor_load", "diff_pair"
        ports: dict[str, PortSpec]         # named interface ports
        devices: list[DeviceSpec]          # internal devices
        local_nodes: list[str]            # internal node names (before prefix renaming)
        local_incidence: IncidenceMatrix  # internal connectivity
        micro_dag_template: list[DAGNode] # per-device analysis steps
        small_signal_summary_rule: str    # which rule computes Av/Rin/Rout for this stage

Ports are not just connection points — they carry semantic information needed 
for automatic composition: what kind of signal, what impedance level, what 
DC voltage range is acceptable. This enables the compositor to check 
compatibility before wiring.

### D2: Two categories of building blocks

A. Signal stages (have input → output signal path):
   CS core, SF core, CG core, Cascode stack, Differential pair.
   These have ports with kind="input" and kind="output".

B. Load / bias blocks (provide load, bias, or current reference):
   Resistor load, Current source load, Current mirror load,
   Active load, Tail current source.
   These have ports with kind="load", kind="bias", kind="tail", etc.
   They do NOT have a signal input→output path.

A complete amplifier stage = one Signal stage + one or more Load/bias blocks.
Example: CS amplifier = CS core (signal) + Resistor load (load block).
Example: Diff amp = Differential pair (signal) + Current mirror load (load) 
         + Tail current source (bias).

### D3: Port compatibility with three-level result

    class CompatibilityLevel(Enum):
        OK = "ok"
        WARN_LOADING = "warn_loading"
        INVALID = "invalid"

Rules:
- Only output-kind → input-kind connections for signal path 
  (load-kind ports connect to load attachment points)
- signal_type must match (voltage↔voltage, differential↔differential)
- Impedance compatibility:
    low output → high input: OK (best)
    medium output → high input: OK
    high output → low input: WARN_LOADING (heavy loading, gain drops)
    low output → low input: context-dependent (OK for buffer/current-mode)
- DC voltage range: if both ports specify dc_voltage_range, the ranges must 
  overlap. Non-overlapping = INVALID (downstream MOSFET will leave saturation).

Generator can be configured to:
  Level 2A: only OK combinations
  Level 2B: allow WARN_LOADING, include loading analysis in reasoning trace
  Level 2C: allow more non-ideal combinations for adversarial testing

### D4: Incidence matrix composition via Union-Find

Algorithm:
1. Prefix each stage's local nodes with stage_id 
   (e.g., "stage1.drain", "stage2.gate")
2. Prefix each stage's device ids with stage_id 
   (e.g., "stage1.M1", "stage2.M1")
3. Create a Union-Find structure over all prefixed nodes
4. For each port interconnection (e.g., stage1.vout → stage2.vin):
   uf.union("stage1.vout", "stage2.vin")
5. Merge all supply nodes globally: 
   uf.union("stage1.vdd", "VDD"), uf.union("stage2.vdd", "VDD")
6. Merge all ground nodes globally:
   uf.union("stage1.gnd", "GND"), uf.union("stage2.gnd", "GND")
7. Build global node list from Union-Find representatives
8. Rebuild global IncidenceMatrix from the merged node map

This approach avoids direct matrix manipulation — work with the graph 
(node-terminal connections), then regenerate the matrix from the graph.

### D5: Three-level DAG template generation

Device-level DAG (per MOSFET, topology-agnostic):
  For each MOSFET in the composed circuit, emit the standard micro-DAG:
  VOV, ID, gm, ro, saturation_check.
  Same rule functions for every MOSFET regardless of its role.
  Node ids prefixed with device id (e.g., "stage1.M1.gm").

Stage-level DAG (per stage, stage-type-specific):
  Each stage's StageSpec declares a small_signal_summary_rule that combines
  its device parameters into stage-level metrics: Av_stage, Rin_stage, Rout_stage.
  Example: CS core uses rule_cs_voltage_gain; SF core uses rule_sf_voltage_gain.

Composition-level DAG (inter-stage, auto-generated):
  For each interconnection between stages:
    loading_factor = Rin_next / (Rout_prev + Rin_next)
    Av_loaded = Av_prev * loading_factor
  For the overall circuit:
    Av_total = product of all Av_loaded values
    Rin_total = Rin of first stage
    Rout_total = Rout of last stage
  High-frequency: dominant pole from output node RC time constant.

Template auto-generation algorithm:
  1. For each stage instance: copy its micro_dag_template with prefixed node ids
  2. For each stage: append stage summary DAG (Av_i, Rin_i, Rout_i)
  3. For each interconnection: append loading factor DAG
  4. For the whole circuit: append composition DAG (Av_total, Rin_total, Rout_total)
  5. Append high-frequency DAG (Cout, dominant pole)

### D6: Backward compatibility with Level 1

Level 1's hand-written templates (CS_RESISTOR_TEMPLATE, SF_RESISTOR_TEMPLATE, 
etc.) remain in templates.py as test golden references. The auto-generated 
template for a single-stage CS+R composition must produce the same DAG 
structure and numerical results as CS_RESISTOR_TEMPLATE.

Level 1 generators also remain functional — they are used for quick 
single-topology generation without the composition overhead.

Layer 1 (rules.py) and Layer 2 (dag_executor.py) require ZERO changes 
for Level 2 to work. Level 2 only extends Layer 3 (template generation).

### D7: Composition validity — three-layer guarantee

Layer 1 — Hard constraints (physical validity):
  All MOSFETs in saturation (VDS >= VOV for each device).
  All node voltages within 0 to VDD.
  No floating nodes (every node connects to at least two terminals).
  No shorts (VDD not directly connected to GND).
  Checked by SPICE .op analysis after circuit generation.
  Failure = discard sample.

Layer 2 — Soft constraints (engineering reasonableness):
  First stage should have high input impedance (CS, diff pair, SF — not CG,
  which has Rin ≈ 1/gm; exception: TIA applications where CG is correct).
  CG only in specific roles: inside cascode stack, or TIA first stage.
  No consecutive SF stages (each SF has gain < 1, cascading just attenuates).
  Total voltage gain |Av_total| > 1 for amplifier circuits.
  Configurable: soft constraints can be relaxed for research/adversarial datasets.
  Failure = discard with log entry, but parametrizable.

Layer 3 — Probability weights (distribution realism):
  Classic textbook combinations get higher sampling weight.
  Unusual-but-valid combinations get lower weight.
  Physically invalid combinations get weight 0.
  Weights stored in config/composition_weights.yaml, editable without code changes.

  Example weights:
    ("diff_pair", "current_mirror_load"): 10  (textbook classic)
    ("cs", "resistor_load"): 8
    ("cascode", "current_source_load"): 8
    ("cs_then_sf"): 6  (gain stage + buffer)
    ("cg", "resistor_load"): 2  (uncommon but valid)
    ("sf", "sf"): 0  (pointless)

### D8: Variance dimensions

Dimension 1 — Topology combination:
  signal_stage_type × load_block_type × num_stages.
  Single stage: ~25 combinations. Two stages: ~625. Three stages: ~15000+.
  True combinatorial growth, not a fixed menu.

Dimension 2 — Parameter randomization:
  Each combination has ~8-12 continuous parameters (VDD, kn, Vth, RD, W/L, 
  lambda, CL, Cgd, etc.) independently sampled from engineering-reasonable ranges.
  Same topology, different parameters = different Q-point, different gain,
  different bandwidth.

Dimension 3 — Structural variants (Phase 3+, not in scope now):
  Source degeneration (Rs in CS source).
  Folded vs telescopic cascode.
  NMOS vs PMOS input differential pair.
  Simple vs cascode current mirror.
  Diode-connected MOSFET loads.

Phase 2 targets Dimension 1 + 2. Dimension 3 is Phase 3+.

### D9: Extensibility path for new components

New components (diode-connected MOSFET, BJT, inductor, transmission gates, 
etc.) are added as:
1. A new StageSpec or DeviceSpec definition
2. New rule functions in rules.py (only if new physics is involved)
3. A new entry in composition_weights.yaml
4. No changes to compositor, executor, Union-Find merger, or existing stages

The first planned extension after Level 2 framework validation: 
diode-connected MOSFET as a load variant. This serves as the "proof of 
extensibility" — if it integrates cleanly, the framework works.

## Consequences

1. New stage types require only: a StageSpec definition + possibly new rules.
   No changes to executor, compositor, or existing stages.
2. Random topology generation = random stage selection + random port wiring
   + feasibility check (port compatibility + DC level + saturation).
3. Multi-stage amplifiers (diff pair + mirror load + CS second stage) are
   naturally supported by composing 3+ StageSpecs.
4. The composition DAG auto-generates the reasoning trace, including
   inter-stage loading analysis — no hand-written template needed.
5. Soft constraints and probability weights are configurable, supporting
   both "textbook-realistic" and "adversarial" dataset generation modes.
6. Level 1 code remains fully functional as a fast path for simple circuits
   and as test golden references for Level 2 auto-generation.

## Relationship to other ADRs
- ADR-006: Level 2 extends Layer 3 of the three-layer DAG architecture.
  Layers 1 and 2 are unchanged.
- ADR-003: Approximation policy applies to all auto-generated traces.
- ADR-004: Hand-calc remains oracle; SPICE cross-checks composed circuits.

## Reference
- docs/design_notes.md §2 (Port definitions — to be updated to match PortSpec)
- docs/design_notes.md §4 (Grammar rules — to be replaced by composition rules)
- src/solver/templates.py (Level 1 hand-written templates = Level 2 test golden)