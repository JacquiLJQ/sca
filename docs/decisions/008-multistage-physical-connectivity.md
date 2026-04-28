# ADR 008: Multi-Stage Circuits Must Be Physically Connected

## Status
Accepted, 2026-04-28. Supersedes the "independently biased" approach
in random_compositor.py's original docstring.

## Context
Level 2 multi-stage circuits were generated with each stage physically
independent — sharing only VDD/GND but no inter-stage signal connections.
The cascade relationship existed only in the DAG template (mathematically
multiplying individual stage gains).

This caused four cascading failures:
1. SPICE netlist contained N independent single-stage circuits, not one
   multi-stage amplifier. ngspice simulated them separately.
2. netlist_writer added V_ bias sources to every "input" role node,
   clamping inter-stage nodes that should be driven by the previous stage.
3. All MOSFET shared one .MODEL (one KP value), but DAG used per-stage
   kn values — SPICE and DAG analyzed different circuits.
4. validation.log found no matching keys (VD vs VD_s1) and no matching
   SPICE nodes (vo vs drain_sig_s2), resulting in all-SKIP false PASS.

## Decision
Multi-stage circuits must be physically connected end-to-end:

### D1: Inter-stage signal wiring is mandatory
generate_composed_circuit must add interconnections:
    stage_i.output_port → stage_{i+1}.input_port
for every adjacent stage pair. The compositor's Union-Find merges these
into a single physical node. The resulting Circuit is one connected
amplifier, not N independent circuits.

### D2: Merged inter-stage nodes get role="internal"
When compositor merges an output port node with an input port node,
the resulting node's role must be "internal" (not "input" or "output").
Only the first stage's input and the last stage's output keep their
signal roles. This prevents netlist_writer from adding V_ bias sources
to inter-stage nodes — they are driven by the previous stage's output,
not by an external voltage source.

### D3: Per-device .MODEL in SPICE netlist
Each MOSFET in a multi-stage circuit may have different kn (= mun_Cox * W/L),
Vth, and lambda. netlist_writer must generate a separate .MODEL for each
MOSFET whose parameters differ from others.

Implementation: model name = f"NMOS_{device_id}" (e.g., NMOS_M1_sig_s1).
Each MOSFET line references its own model. This is always correct
regardless of whether parameters happen to be identical.

build_model_params must accept per-device parameters from the given dict
(reading suffixed keys like kn_s1, Vth_s2, lambda_s3) and produce a
per-device model_params structure.

### D4: Validation must be per-stage aware
For multi-stage circuits, validation.log compares:
- Per-stage: final_values[f"VD_s{i}"] vs corresponding SPICE node voltage
- Per-stage: final_values[f"ID_s{i}"] vs corresponding SPICE device current
- Per-stage: final_values[f"gm_s{i}"] vs corresponding SPICE device gm
- Overall: Av_total (DAG) vs SPICE AC gain (if available)

The mapping from DAG symbol names to SPICE node/device names must be
deterministic and documented (derived from compositor's node naming rules).

### D5: Single pipeline for all circuit complexity
The data flow is:
    StageSpecs → compositor (Union-Find merge) → single Circuit
    → netlist_writer → single .cir → ngspice → SpiceResult
    → validation (per-stage DAG vs SPICE comparison)

This pipeline is the same for 1-stage and N-stage circuits.
Single-stage is just the N=1 special case.

## Consequences
1. random_compositor.py's "independently biased" design is retired.
2. netlist_writer needs per-device .MODEL support.
3. compositor's _merge_role must return "internal" for inter-stage nodes.
4. serializer's validation logic must handle suffixed keys.
5. DC bias chaining (stage i+1 input DC = stage i output DC) is now
   enforced both in the DAG (parameter generation) AND in the physical
   circuit (same node). If there is a discrepancy, SPICE will show it.

## Relationship to other ADRs
- ADR-004: SPICE validates hand-calc. This ADR ensures SPICE actually
  simulates the intended multi-stage circuit, not N independent ones.
- ADR-007: Level 2 composition architecture. This ADR fixes the physical
  connectivity gap in D4 (Union-Find merge) that was not fully implemented.
