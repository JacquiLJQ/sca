"""Batch circuit QA sample generator.

Usage:
    # Level 1 (single-stage, original topologies)
    python -m scripts.generate_batch --count 100 --output-dir data/raw --spice

    # Level 2 (multi-stage composed, random pool)
    python -m scripts.generate_batch --level 2 --count 50 --output-dir data/raw_l2 --spice --max-stages 3
"""

import argparse
import random
import sys
from dataclasses import dataclass, field
from pathlib import Path

from src.packager.pipeline import (
    generate_and_solve_composed_sample,
    generate_and_solve_sample,
)

# Stage distribution for level 2: weights for num_stages = 1, 2, 3
_STAGE_WEIGHTS = [0.15, 0.35, 0.5]


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
    level: int = 1,
    max_stages: int = 2,
) -> BatchResult:
    """Generate `count` samples starting from seed `seed_start`.

    For level 1: calls generate_and_solve_sample (original single-stage pipeline).
    For level 2: calls generate_and_solve_composed_sample with num_stages drawn
        from [1..max_stages] using weights [50%, 35%, 15%] (re-normalised).

    Skips seeds that raise ValueError or RuntimeError and records them in
    failed_seeds. Prints progress every 10 samples.
    """
    output_dir.mkdir(parents=True, exist_ok=True)
    result = BatchResult()
    _rng = random.Random(seed_start)  # for stage-count sampling (level 2)

    for i in range(count):
        seed = seed_start + i
        try:
            if level == 1:
                sample_dir = generate_and_solve_sample(
                    seed=seed,
                    output_dir=output_dir,
                    run_spice_check=run_spice,
                )
            else:
                weights = _STAGE_WEIGHTS[:max_stages]
                stages  = list(range(1, max_stages + 1))
                num_stages = _rng.choices(stages, weights=weights)[0]
                sample_dir = generate_and_solve_composed_sample(
                    seed=seed,
                    output_dir=output_dir,
                    num_stages=num_stages,
                    run_spice_check=run_spice,
                )

            result.generated += 1
            result.sample_dirs.append(sample_dir)

            val_log = sample_dir / "validation.log"
            if val_log.exists() and "WARNING" in val_log.read_text():
                result.spice_warnings += 1

        except (ValueError, RuntimeError) as exc:
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
        description="Batch-generate circuit QA samples."
    )
    parser.add_argument("--count",      type=int,  default=100,
                        help="Number of samples to generate (default: 100)")
    parser.add_argument("--output-dir", type=Path, default=Path("data/raw"),
                        help="Root output directory (default: data/raw)")
    parser.add_argument("--seed-start", type=int,  default=0,
                        help="First RNG seed (default: 0)")
    parser.add_argument("--level",      type=int,  default=1, choices=[1, 2],
                        help="Generation level: 1=single-stage, 2=multi-stage composed (default: 1)")
    parser.add_argument("--max-stages", type=int,  default=2,
                        help="Max stages for level 2 (1–3, default: 2)")
    parser.add_argument("--spice",      action="store_true",  default=True,
                        help="Run ngspice cross-check (default: on)")
    parser.add_argument("--no-spice",   dest="spice", action="store_false",
                        help="Skip ngspice cross-check")
    args = parser.parse_args()

    if args.level == 2 and not (1 <= args.max_stages <= 3):
        parser.error("--max-stages must be 1, 2, or 3")

    result = run_batch_generation(
        count=args.count,
        output_dir=args.output_dir,
        run_spice=args.spice,
        seed_start=args.seed_start,
        level=args.level,
        max_stages=args.max_stages,
    )

    print(
        f"\nGenerated {result.generated}/{args.count} samples, "
        f"{len(result.failed_seeds)} failed, "
        f"{result.spice_warnings} with SPICE warnings"
    )


if __name__ == "__main__":
    main()
