"""Batch CS circuit QA sample generator.

Usage:
    python -m scripts.generate_batch --count 100 --output-dir data/raw --spice
"""

import argparse
import sys
from dataclasses import dataclass, field
from pathlib import Path

from src.packager.pipeline import generate_and_solve_sample


@dataclass
class BatchResult:
    generated: int = 0
    failed_seeds: list[int] = field(default_factory=list)
    spice_warnings: int = 0
    sample_dirs: list[Path] = field(default_factory=list)


def run_batch_generation(
    count: int,
    output_dir: Path,
    run_spice: bool = True,
    seed_start: int = 0,
) -> BatchResult:
    """Generate `count` samples, starting from seed `seed_start`.

    Skips seeds that raise ValueError (infeasible parameter sets) and
    records them in failed_seeds. Prints progress every 10 samples.
    Writes failed_seeds.txt to output_dir if any failures occurred.

    Returns a BatchResult with generation statistics.
    """
    output_dir.mkdir(parents=True, exist_ok=True)
    result = BatchResult()

    for i in range(count):
        seed = seed_start + i
        try:
            sample_dir = generate_and_solve_sample(
                seed=seed,
                output_dir=output_dir,
                run_spice_check=run_spice,
            )
            result.generated += 1
            result.sample_dirs.append(sample_dir)

            val_log = sample_dir / "validation.log"
            if val_log.exists() and "WARNING" in val_log.read_text():
                result.spice_warnings += 1

        except ValueError as exc:
            result.failed_seeds.append(seed)
            print(f"[SKIP] seed={seed}: {exc}", file=sys.stderr)

        if (i + 1) % 10 == 0:
            print(f"Generated {i + 1}/{count}...", flush=True)

    if result.failed_seeds:
        (output_dir / "failed_seeds.txt").write_text(
            "\n".join(str(s) for s in result.failed_seeds) + "\n"
        )

    return result


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Batch-generate CS circuit QA samples."
    )
    parser.add_argument("--count",      type=int,  default=100,
                        help="Number of samples to generate (default: 100)")
    parser.add_argument("--output-dir", type=Path, default=Path("data/raw"),
                        help="Root output directory (default: data/raw)")
    parser.add_argument("--seed-start", type=int,  default=0,
                        help="First RNG seed; seeds are seed_start … seed_start+count-1")
    parser.add_argument("--spice",      action="store_true",  default=True,
                        help="Run ngspice cross-check (default: on)")
    parser.add_argument("--no-spice",   dest="spice", action="store_false",
                        help="Skip ngspice cross-check")
    args = parser.parse_args()

    result = run_batch_generation(
        count=args.count,
        output_dir=args.output_dir,
        run_spice=args.spice,
        seed_start=args.seed_start,
    )

    print(
        f"\nGenerated {result.generated}/{args.count} samples, "
        f"{len(result.failed_seeds)} failed, "
        f"{result.spice_warnings} with SPICE warnings"
    )


if __name__ == "__main__":
    main()
