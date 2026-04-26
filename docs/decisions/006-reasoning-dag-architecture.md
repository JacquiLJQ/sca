# ADR 006: Three-Layer DAG Architecture for Reasoning Chain Generation

## Status
Accepted, 2026-04-26.

## Context
The project needs to generate 8-step reasoning traces (per docs/skill.md) 
for each circuit. The naive approach — calling SymPy to solve equations at 
each step — has fundamental problems:

1. SymPy solves equations but doesn't explain *why* an equation was chosen. 
   The reasoning value is in the "why", not the "solve".
2. SymPy's symbolic solver hits combinatorial explosion on multi-device 
   circuits (cubic+ equations for Q-points with multiple coupled MOSFETs).
3. SymPy is a black box — you can't control the solution path, which means 
   you can't generate a deterministic, topology-aware reasoning trace.

## Decision
Use a three-layer DAG (Directed Acyclic Graph) architecture instead of 
SymPy-driven equation solving.

### Layer 1: Rule Library (src/solver/rules.py)
- ~30 pure functions, each encoding one physics formula.
- Each function takes scalar inputs and returns a RuleResult containing:
  (value, formula_latex, justification, approximations).
- Rules do NOT know what circuit they are in. They only do arithmetic.
- Rules never import Circuit, IncidenceMatrix, or any topology code.
- SymPy is NOT used at runtime. Only math and dataclasses.

Example:
```python
def rule_transconductance(kn: float, VOV: float) -> RuleResult:
    return RuleResult(
        value=kn * VOV,
        formula_latex=r"g_m = k_n \cdot V_{OV}",
        justification="Small-signal transconductance: dID/dVGS in saturation",
        approximations=[],
    )
```

### Layer 2: DAG Executor (src/solver/dag_executor.py)
- Takes a DAG template (list of DAGNode) and a dict of given values.
- Walks the DAG in topological order.
- For each node: gathers inputs from already-resolved values, calls the 
  named rule function, stores the output, records a trace entry.
- Completely generic — same executor for all topologies.
- Never contains topology-specific logic.

### Layer 3: Topology Templates (src/solver/templates.py)
- Each topology (CS+R, SF+R, Cascode, DiffPair, etc.) has a DAG template: 
  an ordered list of DAGNode specifying which rules to call in what order.
- Phase 1: templates are hand-written (CS_RESISTOR_TEMPLATE, etc.).
- Phase 2+: templates for new topologies are hand-written following the 
  same pattern.
- Phase 3 (future): templates are auto-generated from incidence matrix + 
  stage type annotations, replacing hand-written templates. Layer 1 and 
  Layer 2 code does NOT change when this happens.

### How it scales to complex circuits

Per-device analysis (gm, ro, VOV, ID) uses the SAME rule functions 
regardless of topology — these are "micro-DAG" patterns that repeat for 
each MOSFET.

Topology-specific logic (how to combine gm and ro into Av, Rout, Rin) 
lives ONLY in the template. Adding a new topology = adding a new template 
+ possibly a few new rule functions. The executor never changes.

Multi-stage amplifiers: each stage is analyzed independently using its 
own template, then a "composition" template combines stage-level results 
(Av_total = Av1 * Av2, loading effects at interfaces).

### Where SymPy fits (optional, not required)

- Offline formula verification during development (not at runtime).
- Generating LaTeX strings if hand-writing them is error-prone.
- Solving genuinely algebraic Q-point equations (e.g., SF quadratic) 
  INSIDE a specific rule function — SymPy becomes an implementation 
  detail of one rule, not a system-level dependency.

## Consequences

1. Every rule function in rules.py must be pure, scalar-in scalar-out, 
   and return RuleResult. No exceptions.
2. dag_executor.py must be topology-agnostic. If you find yourself writing 
   "if topology == 'cs'" inside the executor, the logic belongs in 
   templates.py instead.
3. templates.py DAGNode lists must be in valid topological order (each 
   node's input_ids must refer to nodes earlier in the list or to given 
   values).
4. The trace output format must match docs/design_notes.md §6 
   (step_number, step_name, inputs, actions, derivations, outputs, 
   justification).
5. Adding a new topology in Phase 2+ should require ZERO changes to 
   rules.py (unless new physics is involved) and ZERO changes to 
   dag_executor.py.

## Relationship to other ADRs

- ADR-003: Approximation policy. Rule functions declare their 
  approximations in the `approximations` field of RuleResult.
- ADR-004: Hand-calc as oracle. The DAG produces hand-analysis results; 
  SPICE cross-checks them.
- ADR-005: YAML numeric loading. Given values fed to the DAG may come 
  from YAML and need float() casting.

## Reference
- docs/skill.md (8-step analysis procedure mapped to DAG steps)
- docs/design_notes.md §6 (reasoning trace JSON schema)
