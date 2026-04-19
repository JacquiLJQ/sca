# ADR 002: SI Unit Convention for All Machine-Readable Outputs

## Status
Accepted, 2026-04-18

## Context
During manual derivation of Case 2 (NMOS CS with ideal current-source load), a unit
inconsistency was found: `gm` was written as `0.396` in one working draft, which looks
like the engineering-unit value in mA/V but would be interpreted as 0.396 A/V (= 396 mA/V)
if read as SI. This produces an Av error of 1000×, which passes all type checks but is
physically wrong.

A second instance was found immediately after: `golden_cs_resistor_load.yaml` stores
`Cout_total: 106.25` (the correct value is 106.25 fF = 106.25e-15 F). The downstream
pole values were computed correctly (treating the number as fF), confirming that the
value was intended as femtofarads but recorded without the SI scaling.

## Decision

All machine-readable files use base SI units exclusively. Affected files:

- `tests/golden/*.yaml`
- `circuit.json`, `problem.json`, `solution.json`, `traces.jsonl`
- Any Python data structure or pydantic model field holding a physical quantity

Engineering prefixes (mA, kΩ, fF, μm, mA/V, etc.) are prohibited as bare numbers
in these files. They may appear only in comments, markdown prose, or human-readable
labels for clarity.

The full unit table is specified in `docs/design_notes.md § 3A`.

## Trigger

Found during Case 2 golden-file review on 2026-04-18. The bug in
`golden_cs_resistor_load.yaml` (`Cout_total: 106.25` instead of `106.25e-15`) was
identified as a direct consequence of the absence of a written unit contract.

## Consequences

1. **Immediate fix required**: `golden_cs_resistor_load.yaml` line 45:
   `Cout_total: 106.25` → `106.25e-15`.

2. **All future golden YAML files** must pass a unit sanity check before being committed.
   A future linter/validator (Module D or a pre-commit hook) should flag any capacitance
   value > 1e-6, transconductance value > 1e-1, or resistance value < 1 as likely unit errors.

3. **Solver, symbolic, and SPICE wrapper code** must read and write physical quantities
   in SI. Any conversion from engineering units (e.g., reading a human-supplied "80 uA")
   must happen at the boundary (input parser), not inside the computation chain.

4. **Claude Code default assumption**: when writing or reading any numeric field for a
   physical quantity in this project, assume SI unless a field name suffix explicitly
   indicates otherwise (e.g., `_uA`, `_mV`, `_fF` suffixes are permitted only for
   human-facing display fields, never for computation fields).

## Supersedes
Nothing. Extends ADR 001 (D3, D9) with a unit-specific contract.

## Reference
- `docs/design_notes.md § 3A` — unit table and precision conventions
- `tests/golden/golden_cs_resistor_load.yaml` line 45 — the triggering bug
