# ADR 004: Hand-calculation as Oracle, SPICE as Verified Executor

## Status
Accepted, 2026-04-18. Complements ADR-003.

## Context
When running the first end-to-end SPICE smoke test on Case 1, the ngspice 
output gave VD ≈ 0.04V instead of the expected 1.0V. Investigation showed 
the mismatch came from a semantic ambiguity in the `kn` parameter: our 
hand calculations use `kn = μn·Cox·(W/L)` as an aggregated "full device 
transconductance parameter", while ngspice's `KP` is strictly 
`μn·Cox` (per-square), with W/L applied separately. The writer was passing 
our aggregated `kn` as `KP`, causing ngspice to effectively multiply W/L 
twice.

The deeper question: when there is a mismatch, which side is authoritative?

## Decision
Golden cases (hand-calculated results) are the oracle. SPICE is the 
verified executor.

If ngspice results disagree with a golden case, the default hypothesis is:
1. The netlist_writer did not translate our modeling conventions faithfully 
   into ngspice parameters, OR
2. The assumptions encoded in the golden case were not stated precisely 
   enough for the writer to translate correctly.

Golden cases themselves are not adjusted to match SPICE.

## Consequences
- Golden YAML syntax must state all modeling assumptions explicitly and 
  precisely (e.g., separating `μn·Cox` from `W/L` rather than aggregating 
  into `kn`).
- netlist_writer is responsible for faithful semantic translation: reading 
  our conventions and emitting ngspice-compatible parameters that produce 
  the same physics.
- When debugging SPICE mismatches, the first suspect is the writer or the 
  assumption declaration, not the hand-calculation.

## Relationship to ADR-003
ADR-003 sets tolerance at 5% to accept first-order engineering approximations.
This ADR clarifies the direction of that tolerance: SPICE may deviate from 
golden within 5%, but golden is what SPICE is being measured against, not 
the reverse.

## Reference
- Case 1 smoke test discrepancy (VD = 0.04V vs 1.0V, 2026-04-18).
- docs/design_notes.md §5 (Verification Strategy).
- docs/decisions/003-approximation-first-ground-truth.md.
