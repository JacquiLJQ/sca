"""Layer 2 of the reasoning DAG: topology-agnostic executor.

See ADR-006 for architecture overview. The executor walks a DAG
template in order, calls rule functions from Layer 1, and produces
a structured ReasoningTrace that can be serialized to traces.jsonl.
"""

import inspect
from collections.abc import Callable
from dataclasses import dataclass, field

from src.solver.rules import RuleResult


@dataclass(frozen=True)
class DAGNode:
    id: str             # unique identifier, e.g. "VOV", "ID", "gm"
    step: int           # skill.md step number (1–8)
    rule_name: str      # function name in rules.py
    input_ids: list[str]   # keys in resolved dict or given dict, in call order
    output_symbol: str  # key written into resolved dict after execution


@dataclass
class TraceEntry:
    step_number: int
    step_name: str               # canonical name from STEP_NAMES
    node_id: str
    rule_name: str
    inputs: dict[str, float]     # {input_id: value} actually passed to the rule
    output_symbol: str
    output_value: float
    formula_latex: str
    justification: str
    approximations: list[str]


@dataclass
class ReasoningTrace:
    entries: list[TraceEntry]
    final_values: dict[str, float]   # all given + all derived values


STEP_NAMES: dict[int, str] = {
    1: "recognize_topology",
    2: "dc_reduction",
    3: "qpoint_solve",
    4: "qpoint_verify",
    5: "small_signal_extraction",
    6: "low_frequency_analysis",
    7: "high_frequency_analysis",
    8: "pole_zero_analysis",
}


def execute_reasoning_dag(
    template: list[DAGNode],
    given: dict[str, float],
    rules: dict[str, Callable[..., RuleResult]] | None = None,
) -> ReasoningTrace:
    """Walk the DAG template in order and produce a full ReasoningTrace.

    Args:
        template:  Ordered list of DAGNode; must be in valid topological order.
        given:     Problem-given values (e.g. VDD, RD, kn). Not mutated.
        rules:     Optional explicit rule registry {function_name: function}.
                   If None, all functions named "rule_*" in src.solver.rules
                   are collected automatically.

    Returns:
        ReasoningTrace with one TraceEntry per DAGNode, plus final_values
        containing every given and derived quantity.

    Raises:
        KeyError:  A node references an input_id not yet resolved.
        ValueError: A node references a rule_name not present in the registry.
    """
    if rules is None:
        from src.solver import rules as _rules_module
        rules = {
            name: fn
            for name, fn in inspect.getmembers(_rules_module, inspect.isfunction)
            if name.startswith("rule_")
        }

    resolved: dict[str, float] = dict(given)
    entries: list[TraceEntry] = []

    for node in template:
        # Gather inputs in the order declared by input_ids.
        inputs: dict[str, float] = {}
        for input_id in node.input_ids:
            if input_id not in resolved:
                raise KeyError(
                    f"node '{node.id}' needs '{input_id}' but it is not in "
                    "resolved values or given dict"
                )
            inputs[input_id] = resolved[input_id]

        # Look up the rule function.
        if node.rule_name not in rules:
            raise ValueError(
                f"rule '{node.rule_name}' not found in registry; "
                f"available: {sorted(rules.keys())}"
            )
        rule_fn = rules[node.rule_name]

        # Call with positional args in input_ids order (ADR-006: template author
        # guarantees input_ids order matches the rule function signature).
        result: RuleResult = rule_fn(*[resolved[iid] for iid in node.input_ids])

        # Persist the derived value.
        resolved[node.output_symbol] = result.value

        entries.append(
            TraceEntry(
                step_number=node.step,
                step_name=STEP_NAMES[node.step],
                node_id=node.id,
                rule_name=node.rule_name,
                inputs=inputs,
                output_symbol=node.output_symbol,
                output_value=result.value,
                formula_latex=result.formula_latex,
                justification=result.justification,
                approximations=list(result.approximations),
            )
        )

    return ReasoningTrace(entries=entries, final_values=resolved)
