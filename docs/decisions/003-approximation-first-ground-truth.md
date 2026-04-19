# ADR 003: Approximation-First Ground Truth

## Status
Accepted, 2026-04-18. Supersedes the numerical-ground-truth stance in ADR-001.

## Context
During Case 3 (Source Follower) construction, the first-order Q-point
approximation (ignoring λ in DC solve) produced a VOV that deviated ~1%
from the exact numerical solution — right at the edge of the original
1% tolerance. This forced a choice:
- Require exact numerical Q-points in golden cases, OR
- Allow engineering approximations and widen the tolerance.

User reasoning: "In real circuit analysis, over-precision has limited
value. What matters is the reasoning/analysis process."

## Decision
Golden cases and reasoning traces use first-order engineering approximations
as the primary truth. SPICE provides sanity checking within 5% tolerance,
not exact comparison.

## Consequences
- Tolerance raised from 1% to 5% for golden-case verification.
- SPICE reframed as independent verification path, not absolute ground truth.
- Samples with 5–20% deviation are flagged for review, not auto-discarded.
- Samples with >20% deviation are discarded as genuinely incorrect.
- Reasoning traces must explicitly list approximations applied.
- Training signal captures engineering judgment, not numerical precision.
- Solver implementations may use either symbolic hand-analysis or numerical
  methods, but golden YAML values reflect the hand-analysis result.

## Reference
- docs/design_notes.md §5 (updated).
- Case 3 discussion that triggered this ADR.
