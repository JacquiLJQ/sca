"""End-to-end sample generation pipeline: Module A → Module C → serialization."""

from pathlib import Path

from src.solver.dag_executor import execute_reasoning_dag
from src.solver.spice_runner import run_spice
from src.solver.templates import (
    CASCODE_RESISTOR_TEMPLATE,
    CG_RESISTOR_TEMPLATE,
    CS_IDEAL_CURRENT_SOURCE_TEMPLATE,
    CS_RESISTOR_TEMPLATE,
    SF_RESISTOR_TEMPLATE,
)
from src.topology.generator import (
    generate_cascode_resistor_circuit,
    generate_cg_resistor_circuit,
    generate_cs_current_source_circuit,
    generate_cs_resistor_circuit,
    generate_random_circuit,
    generate_sf_resistor_circuit,
)
from src.topology.random_compositor import generate_composed_circuit
from src.utils.model_params import build_model_params
from src.utils.netlist_writer import circuit_to_netlist
from src.packager.serializer import serialize_sample


# Maps topo_key → (generator_fn, dag_template)
_REGISTRY = {
    "cs_resistor":       (generate_cs_resistor_circuit,       CS_RESISTOR_TEMPLATE),
    "sf_resistor":       (generate_sf_resistor_circuit,       SF_RESISTOR_TEMPLATE),
    "cs_current_source": (generate_cs_current_source_circuit, CS_IDEAL_CURRENT_SOURCE_TEMPLATE),
    "cg_resistor":       (generate_cg_resistor_circuit,       CG_RESISTOR_TEMPLATE),
    "cascode_resistor":  (generate_cascode_resistor_circuit,  CASCODE_RESISTOR_TEMPLATE),
}


def generate_and_solve_sample(
    seed: int | None = None,
    output_dir: Path = Path("data/raw"),
    run_spice_check: bool = True,
    topology: str | None = None,
) -> Path:
    """Generate a circuit sample, solve it with the DAG, serialize, and return its path.

    Args:
        seed:            RNG seed for reproducible generation.
        output_dir:      Root directory; sample is written to output_dir/<sample_id>/.
        run_spice_check: If True, run ngspice .op and include validation.log.
        topology:        Topology key (e.g. "cs_resistor", "cascode_resistor").
                         If None, a topology is chosen at random via generate_random_circuit.

    Returns: Path to the sample directory.
    Raises:  ValueError if topology is unrecognised.
    """
    if topology is not None:
        if topology not in _REGISTRY:
            raise ValueError(
                f"Unknown topology '{topology}'. "
                f"Valid keys: {sorted(_REGISTRY)}"
            )
        gen_fn, template = _REGISTRY[topology]
        circuit, given = gen_fn(seed=seed)
        topo_key = topology
    else:
        circuit, given, topo_key = generate_random_circuit(seed=seed)
        _, template = _REGISTRY[topo_key]

    trace = execute_reasoning_dag(template, given)

    spice_result = None
    if run_spice_check:
        netlist = circuit_to_netlist(circuit, model_params=build_model_params(given))
        spice_result = run_spice(netlist, analysis="op")

    sample_dir = output_dir / circuit.sample_id
    return serialize_sample(
        sample_dir, circuit, given, trace, spice_result,
        topology=topo_key,
    )


def generate_and_solve_composed_sample(
    seed: int | None = None,
    output_dir: Path = Path("data/raw"),
    num_stages: int = 2,
    run_spice_check: bool = True,
) -> Path:
    """Generate a multi-stage composed circuit, solve with the DAG, serialize.

    Args:
        seed:            RNG seed for reproducible generation.
        output_dir:      Root directory; sample written to output_dir/<sample_id>/.
        num_stages:      Number of amplifier stages (1, 2, or 3).
        run_spice_check: If True, run ngspice .op and include circuit.cir.

    Returns: Path to the sample directory.
    """
    result = generate_composed_circuit(seed=seed, num_stages=num_stages)
    trace  = execute_reasoning_dag(result.template, result.given)

    spice_result = None
    if run_spice_check:
        netlist      = circuit_to_netlist(
            result.circuit,
            model_params=build_model_params(result.given, circuit=result.circuit),
        )
        spice_result = run_spice(netlist, analysis="op")

    topo_key   = "+".join(result.stage_keys)
    sample_dir = output_dir / result.circuit.sample_id
    return serialize_sample(
        sample_dir, result.circuit, result.given, trace, spice_result,
        topology=topo_key,
    )
