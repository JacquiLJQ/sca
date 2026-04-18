# Project: Synthetic Analog Circuit QA Generator

## Project Goal
This project builds a pipeline that generates (circuit, problem, solution) triples as training data.
- circuit: transistor-level CMOS amplifier composed of basic stages (CS / SF / CG / Cascode / DiffPair) through legal composition
- problem: an analysis question based on the circuit — may ask for Q-point, gain, bandwidth, poles, etc.
- solution: complete answer plus a reasoning trace derived following docs/skill.md
End use: fine-tuning or evaluation data for analog-reasoning LLMs.

## Critical References (read at the start of every session)
- docs/skill.md — the canonical procedure for CMOS analog circuit analysis (8 steps, must be followed strictly)
- docs/template.md — the result recording template (every section must be populated)
- docs/design_notes.md — project design decisions and data structure specifications

## Non-Negotiable Rules
1. Never violate the 8-step order defined in skill.md: bias first, linearize second, frequency third, poles last.
2. Every generated circuit must pass a DC feasibility check before moving to problem generation.
3. Every numerical answer must be cross-validated against SPICE (ngspice) as ground truth.
4. If SymPy is used for symbolic derivation, the symbolic expression — evaluated with given parameters — must match the SPICE result within 1% tolerance, otherwise discard the sample.
5. Template sections in template.md must never be silently omitted. Use "not provided" / "not applicable" / "not derived" for unavailable fields.
6. The incidence matrix is the single source of truth for topology. SPICE netlist, graph representations, and schematics are all derived from it.

## Coding Preferences
- Python 3.10+, all functions and classes must have type hints.
- Data models use pydantic v2, not plain dicts.
- Tests use pytest. Each module has its own test file.
- SPICE is invoked via ngspice (subprocess or PySpice). Do not re-implement SPICE.
- Symbolic computation uses SymPy.
- No additional heavyweight frameworks (no Django / FastAPI / large ML frameworks).

## Workflow Preferences
- Do exactly one well-defined small task at a time. Do not expand scope unilaterally.
- After completing a task, run the relevant tests and paste the output for the user to review.
- When uncertain, ask the user first. Do not guess.
- After each milestone, write an ADR (Architecture Decision Record) in docs/decisions/ capturing key decisions.

## Pipeline Structure (four modules)
- Module A — Topology Generator (src/topology/): produces circuit structure
- Module B — Problem Setter (src/problem/): assigns given parameters and decides what to ask
- Module C — Solver (src/solver/): executes skill.md procedure and generates reasoning traces
- Module D — Packager (src/packager/): deduplicates and assembles the dataset

## Development Phases
- Phase 1 (current): implement single-stage CS only; achieve end-to-end pipeline; target 100 samples.
- Phase 2: add SF / CG / Cascode stages.
- Phase 3: add differential pair and multi-stage amplifiers.
- Phase 4: add folded cascode, feedback, and compensation.

## When Uncertain
If you are unsure about circuit conventions, MOSFET equations, or the scope of a task, ask the user first. Do not guess.