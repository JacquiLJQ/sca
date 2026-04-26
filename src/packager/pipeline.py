"""End-to-end sample generation pipeline: Module A → Module C → serialization."""

from pathlib import Path

from src.solver.dag_executor import execute_reasoning_dag
from src.solver.spice_runner import run_spice
from src.solver.templates import CS_RESISTOR_TEMPLATE
from src.topology.generator import generate_cs_resistor_circuit
from src.utils.model_params import build_model_params
from src.utils.netlist_writer import circuit_to_netlist
from src.packager.serializer import serialize_sample


def generate_and_solve_sample(
    seed: int | None = None,
    output_dir: Path = Path("data/raw"),
    run_spice_check: bool = True,
) -> Path:
    """Generate a random CS circuit sample, solve it, serialize, and return its path.

    Args:
        seed:            RNG seed for reproducible generation.
        output_dir:      Root directory; sample is written to output_dir/<sample_id>/.
        run_spice_check: If True, run ngspice .op and include validation.log.

    Returns: Path to the sample directory.
    """
    circuit, given = generate_cs_resistor_circuit(seed=seed)
    trace = execute_reasoning_dag(CS_RESISTOR_TEMPLATE, given)

    spice_result = None
    if run_spice_check:
        netlist = circuit_to_netlist(circuit, model_params=build_model_params(given))
        spice_result = run_spice(netlist, analysis="op")

    sample_dir = output_dir / circuit.sample_id
    return serialize_sample(sample_dir, circuit, given, trace, spice_result)
