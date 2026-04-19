# ADR 001: Initial Design Contract

## Status
Accepted, 2026-04-18

## Context
Project initialization phase. We needed a stable contract for data structures and pipeline flow before writing any implementation code.

## Decisions

### D1: Four-module pipeline (A → B → C → D)
Topology Generator → Problem Setter → Solver → Packager. Each module's output is the next's input; no cross-module back-references.

### D2: Incidence matrix as single source of truth
Rows = nodes, columns = device terminals (M1.D, M1.G, M1.S, M1.B for MOSFETs; .a/.b for 2-terminal devices). Entry ∈ {0, 1}, exactly one 1 per column. All other representations (SPICE netlist, graph, schematic) derive from it.

### D3: ngspice as ground truth
All numerical answers use ngspice as authoritative. SymPy symbolic expressions must match ngspice within 1% after parameter substitution, or the sample is discarded.

### D4: Supply rails as node attributes, not ports
VDD / VSS / GND are marked via node_metadata[node]["role"], not via Port objects. Port.terminal is restricted to MOSFET terminals G/D/S/B.

### D5: Port types include both signal and bias flavors
Port.type literal: signal_in, signal_out, bias_in, bias_out, supply. signal_* carries small-signal; bias_* carries DC bias current/voltage from generators like current mirrors.

### D6: Composite stages keep internal structure visible
Cascode and similar composite stages are sampled as one token by the grammar but their internal MOSFETs are stored explicitly in device_metadata, enabling Phase 4 unfolding for folded cascode etc.

### D7: DiffPair defined with full differential outputs from Phase 1
out_p and out_n are always defined with cross-referenced differential_partner. Phase 1 controls complexity via grammar (e.g., must be followed by current-mirror load) rather than by truncating port definitions.

### D8: Phase 1 scope is single-stage CS only
No composition is active in Phase 1. Grammar patterns (CS→SF, DiffPair→Mirror, etc.) activate from Phase 2.

### D9: Null + _note convention for undefined numerics
JSON uses null for infinite/undefined values, paired with a sibling _note field explaining why. Markdown reports may use human-readable strings ("not provided") for readability.

### D10: Canonical Phase 1 question types
qpoint, low_freq_gain, input_resistance, output_resistance. Phase 2+ adds dominant_pole, bandwidth_3dB, ugf, phase_margin.

## Consequences
- All implementation code (stages, grammar, solver, packager) must conform to these contracts.
- Changes to these decisions require a new ADR that supersedes the relevant section.
- This ADR pins down the interpretation of design_notes.md as of today.

## Reference
docs/design_notes.md (version as of 2026-04-18).
