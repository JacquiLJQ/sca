"""Dataset packager: aggregates raw samples into dataset.jsonl + stats.

Usage:
    python -m scripts.package_dataset --input-dir data/raw --output data/dataset
"""

import argparse
import json
import statistics
from datetime import datetime, timezone
from pathlib import Path


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _parse_spice_validation(log_path: Path) -> str:
    """Read validation.log and return PASS / WARNING / FAIL / SKIPPED."""
    if not log_path.exists():
        return "SKIPPED"
    lines = log_path.read_text().splitlines()
    overall = next((l for l in reversed(lines) if l.startswith("OVERALL:")), None)
    if overall is None:
        return "SKIPPED"
    if "FAIL" in overall:
        return "FAIL"
    if any("WARNING" in l for l in lines):
        return "WARNING"
    return "PASS"


def _load_sample(sample_dir: Path) -> dict | None:
    """Load one sample directory into a dataset record. Returns None if incomplete."""
    required = ["problem.json", "solution.json", "traces.jsonl"]
    if any(not (sample_dir / f).exists() for f in required):
        return None

    problem  = json.loads((sample_dir / "problem.json").read_text())
    solution = json.loads((sample_dir / "solution.json").read_text())
    traces   = [
        json.loads(line)
        for line in (sample_dir / "traces.jsonl").read_text().splitlines()
        if line.strip()
    ]
    spice_val = _parse_spice_validation(sample_dir / "validation.log")

    return {
        "sample_id":        problem["sample_id"],
        "topology":         problem["topology"],
        "given":            problem["given"],
        "solution":         solution,
        "trace":            traces,
        "spice_validation": spice_val,
    }


def _compute_stats(values: list) -> dict:
    clean = [v for v in values if v is not None]
    if not clean:
        return {"min": None, "max": None, "mean": None, "std": None}
    return {
        "min":  min(clean),
        "max":  max(clean),
        "mean": statistics.mean(clean),
        "std":  statistics.stdev(clean) if len(clean) > 1 else 0.0,
    }


def _fmt_stat_row(label: str, unit: str, st: dict) -> str:
    if st["min"] is None:
        return f"| {label} | N/A | N/A | N/A | N/A |"
    return (
        f"| {label} ({unit}) | {st['min']:.4g} | {st['max']:.4g} | "
        f"{st['mean']:.4g} | {st['std']:.4g} |"
    )


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def run_packaging(
    input_dir: Path,
    output_dir: Path,
) -> tuple[int, list[str]]:
    """Package all samples from input_dir into output_dir/dataset.jsonl.

    Returns (packaged_count, list_of_skipped_sample_ids).
    Also writes output_dir/dataset_stats.md and output_dir/skipped.txt (if any).
    """
    output_dir.mkdir(parents=True, exist_ok=True)

    samples: list[dict] = []
    skipped: list[str]  = []

    for sample_dir in sorted(input_dir.iterdir()):
        if not sample_dir.is_dir() or sample_dir.name.startswith("."):
            continue
        record = _load_sample(sample_dir)
        if record is None:
            skipped.append(sample_dir.name)
        else:
            samples.append(record)

    # Write dataset.jsonl + per-validation splits -------------------------
    pass_samples = [s for s in samples if s["spice_validation"] == "PASS"]
    fail_samples = [s for s in samples if s["spice_validation"] == "FAIL"]

    with (output_dir / "dataset.jsonl").open("w") as fh:
        for s in samples:
            fh.write(json.dumps(s) + "\n")

    with (output_dir / "dataset_pass.jsonl").open("w") as fh:
        for s in pass_samples:
            fh.write(json.dumps(s) + "\n")

    with (output_dir / "dataset_fail.jsonl").open("w") as fh:
        for s in fail_samples:
            fh.write(json.dumps(s) + "\n")

    # Write skipped.txt ---------------------------------------------------
    if skipped:
        (output_dir / "skipped.txt").write_text("\n".join(skipped) + "\n")

    # Collect stats -------------------------------------------------------
    vdd_vals = [s["given"].get("VDD") for s in samples]
    rd_vals  = [s["given"].get("RD")  for s in samples]

    def _get_av(sol: dict) -> float | None:
        # Multi-stage: cascade.Av_total; single-stage: low_frequency.Av
        av = sol.get("cascade", {}).get("Av_total")
        if av is None:
            av = sol.get("low_frequency", {}).get("Av")
        return abs(av) if av is not None else None

    def _get_gm(sol: dict) -> float | None:
        # Single-stage: small_signal.gm; multi-stage: first stage's gm
        gm = sol.get("small_signal", {}).get("gm")
        if gm is None:
            gm = sol.get("stages", {}).get("stage_1", {}).get("small_signal", {}).get("gm")
        return gm

    av_vals = [_get_av(s["solution"]) for s in samples if _get_av(s["solution"]) is not None]
    gm_vals = [_get_gm(s["solution"]) for s in samples if _get_gm(s["solution"]) is not None]

    val_counts: dict[str, int] = {"PASS": 0, "WARNING": 0, "FAIL": 0, "SKIPPED": 0}
    topo_counts: dict[str, int] = {}
    topo_pass: dict[str, int] = {}
    topo_fail: dict[str, int] = {}
    for s in samples:
        val_counts[s["spice_validation"]] += 1
        topo_counts[s["topology"]] = topo_counts.get(s["topology"], 0) + 1
        if s["spice_validation"] == "PASS":
            topo_pass[s["topology"]] = topo_pass.get(s["topology"], 0) + 1
        elif s["spice_validation"] == "FAIL":
            topo_fail[s["topology"]] = topo_fail.get(s["topology"], 0) + 1

    ts = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    topo_rows = "\n".join(f"- {t}: {c}" for t, c in sorted(topo_counts.items()))
    topo_pass_rows = "\n".join(f"- {t}: {c}" for t, c in sorted(topo_pass.items())) or "*(none)*"
    topo_fail_rows = "\n".join(f"- {t}: {c}" for t, c in sorted(topo_fail.items())) or "*(none)*"

    stats_md = "\n".join([
        "# Dataset Statistics",
        "",
        f"Generated: {ts}",
        f"Total samples: {len(samples)}",
        f"Skipped (incomplete): {len(skipped)}",
        "",
        "## SPICE Validation",
        "",
        f"- PASS: {val_counts['PASS']}  → dataset_pass.jsonl",
        f"- WARNING: {val_counts['WARNING']}",
        f"- FAIL: {val_counts['FAIL']}  → dataset_fail.jsonl",
        f"- SKIPPED (no SPICE run): {val_counts['SKIPPED']}",
        "",
        "## Topology Breakdown (all)",
        "",
        topo_rows,
        "",
        "## Topology Breakdown — PASS only",
        "",
        topo_pass_rows,
        "",
        "## Topology Breakdown — FAIL only",
        "",
        topo_fail_rows,
        "",
        "## Parameter Distribution",
        "",
        "| Parameter | Min | Max | Mean | Std |",
        "|---|---|---|---|---|",
        _fmt_stat_row("VDD",  "V",   _compute_stats(vdd_vals)),
        _fmt_stat_row("RD",   "Ω",   _compute_stats(rd_vals)),
        _fmt_stat_row("|Av|", "",    _compute_stats(av_vals)),
        _fmt_stat_row("gm",   "A/V", _compute_stats(gm_vals)),
    ]) + "\n"

    (output_dir / "dataset_stats.md").write_text(stats_md)

    return len(samples), skipped


# ---------------------------------------------------------------------------
# CLI entry point
# ---------------------------------------------------------------------------

def main() -> None:
    parser = argparse.ArgumentParser(
        description="Package raw samples into dataset.jsonl + stats."
    )
    parser.add_argument("--input-dir", type=Path, default=Path("data/raw"),
                        help="Directory containing sample subdirectories")
    parser.add_argument("--output",    type=Path, default=Path("data/dataset"),
                        help="Output directory for dataset files")
    args = parser.parse_args()

    n, skipped = run_packaging(args.input_dir, args.output)
    print(f"Packaged {n} samples, {len(skipped)} skipped.")
    if skipped:
        preview = ", ".join(skipped[:5])
        suffix  = "…" if len(skipped) > 5 else ""
        print(f"Skipped: {preview}{suffix}")


if __name__ == "__main__":
    main()
