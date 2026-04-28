"""Level 2 DAG template generator: composes StageSpec micro-DAG entries into a DAGNode list.

Public API:
    generate_template(signal_spec_or_stages, load_spec=None) → list[DAGNode]

    Single-stage call (backward-compatible):
        generate_template(signal_spec, load_spec)

    Multi-stage call:
        generate_template([(signal1, load1), (signal2, load2), ...])

Emission order follows skill.md step order (ADR-007 D5):
    Step 3:  signal qpoint_entries → load qpoint_entries → signal vds_entries
    Step 4:  signal satcheck_entries → load satcheck_entries
    Step 5:  signal ss_entries → load ss_entries
    Step 6:  load rout_entries → signal gain_entries
    Step 7:  signal hf_entries  (last stage only in multi-stage)
    Step 8:  signal pole_entries (last stage only in multi-stage)

    Multi-stage also appends (after all stages):
    Step 6:  Rin injection → loading_factor → Av_loaded (per adjacent pair)
             cascade gain → Av_total → Av_total_dB
    Step 7:  last-stage hf
    Step 8:  last-stage poles

This module does NOT import compositor.py or any topology module.
"""

from __future__ import annotations

from src.solver.dag_executor import DAGNode
from src.topology.stage_spec import MicroDagEntry, StageSpec

# Given-dict keys that are stage-specific (suffixed with _s{i} in multi-stage mode).
# Shared keys (VDD, CL, Cgd) are NOT in this set.
_STAGE_SPECIFIC_KEYS: frozenset[str] = frozenset({
    "VG_DC", "VG_bias", "Vin_DC",
    "Vth", "kn", "lambda",
    "RD", "Rs_load", "Iload", "VDS_target",
})


def _to_node(e: MicroDagEntry) -> DAGNode:
    return DAGNode(
        id=e.local_id,
        step=e.step,
        rule_name=e.rule_name,
        input_ids=e.input_refs,
        output_symbol=e.output_local,
    )


def _suffix_entry(
    entry: MicroDagEntry,
    sfx: str,
    produced: set[str],
) -> DAGNode:
    """Translate a MicroDagEntry to a DAGNode with stage suffix applied.

    Rules:
    - If (ref + sfx) is already in produced: this ref was computed earlier in
      the same stage → use the suffixed form.
    - Else if ref is in _STAGE_SPECIFIC_KEYS: it is a stage-specific given-dict
      key → append the suffix.
    - Else: it is a shared given-dict key (VDD, CL, Cgd, …) → leave as-is.
    """
    new_ids: list[str] = []
    for ref in entry.input_refs:
        suffixed = ref + sfx
        if suffixed in produced:
            new_ids.append(suffixed)
        elif ref in _STAGE_SPECIFIC_KEYS:
            new_ids.append(suffixed)
        else:
            new_ids.append(ref)

    out_sym = entry.output_local + sfx
    produced.add(out_sym)
    return DAGNode(
        id=entry.local_id + sfx,
        step=entry.step,
        rule_name=entry.rule_name,
        input_ids=new_ids,
        output_symbol=out_sym,
    )


def _emit_stage(
    signal_spec: StageSpec,
    load_spec: StageSpec | None,
    sfx: str,
    produced: set[str],
    include_hf: bool,
) -> list[DAGNode]:
    """Emit all DAG nodes for one stage with the given suffix."""
    nodes: list[DAGNode] = []

    # Step 3
    for e in signal_spec.qpoint_entries:
        nodes.append(_suffix_entry(e, sfx, produced))
    if load_spec:
        for e in load_spec.qpoint_entries:
            nodes.append(_suffix_entry(e, sfx, produced))
    for e in signal_spec.vds_entries:
        nodes.append(_suffix_entry(e, sfx, produced))

    # Step 4
    for e in signal_spec.satcheck_entries:
        nodes.append(_suffix_entry(e, sfx, produced))
    if load_spec:
        for e in load_spec.satcheck_entries:
            nodes.append(_suffix_entry(e, sfx, produced))

    # Step 5
    for e in signal_spec.ss_entries:
        nodes.append(_suffix_entry(e, sfx, produced))
    if load_spec:
        for e in load_spec.ss_entries:
            nodes.append(_suffix_entry(e, sfx, produced))

    # Step 6: Rout then gain
    if load_spec:
        for e in load_spec.rout_entries:
            nodes.append(_suffix_entry(e, sfx, produced))
    for e in signal_spec.gain_entries:
        nodes.append(_suffix_entry(e, sfx, produced))

    # Steps 7+8: only for the last stage
    if include_hf:
        for e in signal_spec.hf_entries:
            nodes.append(_suffix_entry(e, sfx, produced))
        for e in signal_spec.pole_entries:
            nodes.append(_suffix_entry(e, sfx, produced))

    return nodes


def _generate_multistage(
    stages: list[tuple[StageSpec, StageSpec | None]],
) -> list[DAGNode]:
    """Generate a flat DAGNode list for N cascaded stages."""
    n = len(stages)
    nodes: list[DAGNode] = []
    produced: set[str] = set()

    # Emit per-stage device-level + stage-level DAG (no HF for intermediate stages)
    for i, (sig, ld) in enumerate(stages, start=1):
        sfx = f"_s{i}"
        include_hf = (i == n)  # HF/poles only for last stage
        nodes += _emit_stage(sig, ld, sfx, produced, include_hf=include_hf)

    # Ensure Rin_s{i} exists for loading analysis at each stage
    for i, (sig, _ld) in enumerate(stages, start=1):
        sfx = f"_s{i}"
        rin_sym = f"Rin{sfx}"
        if rin_sym not in produced:
            nodes.append(DAGNode(
                id=f"Rin{sfx}",
                step=6,
                rule_name="rule_rin_infinite",
                input_ids=[],
                output_symbol=rin_sym,
            ))
            produced.add(rin_sym)

    # Inter-stage loading: for each adjacent pair (i → i+1)
    # Last stage's gain is the unloaded terminal gain (no further loading node)
    prev_av_sym = "Av_s1"  # first partial cascade
    for i in range(1, n):
        sfx_i   = f"_s{i}"
        sfx_j   = f"_s{i + 1}"
        lf_sym  = f"loading_factor_s{i}_s{i + 1}"
        avl_sym = f"Av_loaded_s{i}"
        nodes.append(DAGNode(
            id=lf_sym, step=6,
            rule_name="rule_loading_factor",
            input_ids=[f"Rout{sfx_i}", f"Rin{sfx_j}"],
            output_symbol=lf_sym,
        ))
        produced.add(lf_sym)
        nodes.append(DAGNode(
            id=avl_sym, step=6,
            rule_name="rule_loaded_gain",
            input_ids=[f"Av{sfx_i}", lf_sym],
            output_symbol=avl_sym,
        ))
        produced.add(avl_sym)

    # Cascade total gain
    # Av_total = Av_loaded_s1 * Av_loaded_s2 * ... * Av_loaded_s{n-1} * Av_s{n}
    if n == 1:
        # Single stage — no cascade node needed; Av is in produced
        pass
    elif n == 2:
        nodes.append(DAGNode(
            id="Av_total", step=6,
            rule_name="rule_cascade_gain",
            input_ids=["Av_loaded_s1", f"Av_s{n}"],
            output_symbol="Av_total",
        ))
        produced.add("Av_total")
    else:
        # Build stepwise: Av_12 = cascade(Av_loaded_s1, Av_loaded_s2), etc.
        prev = "Av_loaded_s1"
        for i in range(2, n):
            cur = f"Av_cascade_s1_to_s{i}"
            nodes.append(DAGNode(
                id=cur, step=6,
                rule_name="rule_cascade_gain",
                input_ids=[prev, f"Av_loaded_s{i}"],
                output_symbol=cur,
            ))
            produced.add(cur)
            prev = cur
        nodes.append(DAGNode(
            id="Av_total", step=6,
            rule_name="rule_cascade_gain",
            input_ids=[prev, f"Av_s{n}"],
            output_symbol="Av_total",
        ))
        produced.add("Av_total")

    if n > 1:
        nodes.append(DAGNode(
            id="Av_total_dB", step=6,
            rule_name="rule_av_to_db",
            input_ids=["Av_total"],
            output_symbol="Av_total_dB",
        ))
        produced.add("Av_total_dB")

    return nodes


def generate_template(
    signal_or_stages: StageSpec | list[tuple[StageSpec, StageSpec | None]],
    load_spec: StageSpec | None = None,
) -> list[DAGNode]:
    """Generate a DAGNode list.

    Single-stage (backward-compatible):
        generate_template(signal_spec)
        generate_template(signal_spec, load_spec)

    Multi-stage:
        generate_template([(sig1, ld1), (sig2, ld2), ...])
    """
    if isinstance(signal_or_stages, list):
        return _generate_multistage(signal_or_stages)

    # Single-stage path (unchanged from original)
    signal_spec: StageSpec = signal_or_stages
    nodes: list[DAGNode] = []

    nodes += [_to_node(e) for e in signal_spec.qpoint_entries]
    if load_spec:
        nodes += [_to_node(e) for e in load_spec.qpoint_entries]
    nodes += [_to_node(e) for e in signal_spec.vds_entries]

    nodes += [_to_node(e) for e in signal_spec.satcheck_entries]
    if load_spec:
        nodes += [_to_node(e) for e in load_spec.satcheck_entries]

    nodes += [_to_node(e) for e in signal_spec.ss_entries]
    if load_spec:
        nodes += [_to_node(e) for e in load_spec.ss_entries]

    if load_spec:
        nodes += [_to_node(e) for e in load_spec.rout_entries]
    nodes += [_to_node(e) for e in signal_spec.gain_entries]

    nodes += [_to_node(e) for e in signal_spec.hf_entries]
    nodes += [_to_node(e) for e in signal_spec.pole_entries]

    return nodes
