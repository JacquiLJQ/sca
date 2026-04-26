"""Integration tests for batch generation and dataset packaging."""

import json
from pathlib import Path

import pytest

from scripts.generate_batch import run_batch_generation
from scripts.package_dataset import run_packaging

EXPECTED_FILES = {
    "circuit.json",
    "circuit.cir",
    "problem.md",
    "problem.json",
    "solution.md",
    "solution.json",
    "traces.jsonl",
    "validation.log",
}


# ---------------------------------------------------------------------------
# Module-scoped fixture: generate 5 samples once for both tests
# ---------------------------------------------------------------------------

@pytest.fixture(scope="module")
def batch_dir(tmp_path_factory) -> tuple[Path, object]:
    tmp = tmp_path_factory.mktemp("batch")
    result = run_batch_generation(
        count=5, output_dir=tmp, run_spice=True, seed_start=0
    )
    return tmp, result


# ---------------------------------------------------------------------------
# Test 1: batch generation
# ---------------------------------------------------------------------------

@pytest.mark.spice
def test_generate_batch_small(batch_dir):
    raw_dir, result = batch_dir

    assert result.generated == 5, \
        f"Expected 5 generated samples, got {result.generated}"
    assert not result.failed_seeds, \
        f"Unexpected failed seeds: {result.failed_seeds}"

    for sample_dir in result.sample_dirs:
        present = {p.name for p in sample_dir.iterdir()}
        assert EXPECTED_FILES <= present, (
            f"{sample_dir.name} missing: {EXPECTED_FILES - present}"
        )


# ---------------------------------------------------------------------------
# Test 2: dataset packaging
# ---------------------------------------------------------------------------

@pytest.mark.spice
def test_package_dataset(batch_dir, tmp_path):
    raw_dir, _ = batch_dir
    dataset_dir = tmp_path / "dataset"

    n, skipped = run_packaging(input_dir=raw_dir, output_dir=dataset_dir)

    assert (dataset_dir / "dataset.jsonl").exists()
    assert (dataset_dir / "dataset_stats.md").exists()
    assert not skipped, f"Unexpected skipped samples: {skipped}"

    lines = [
        l for l in (dataset_dir / "dataset.jsonl").read_text().splitlines()
        if l.strip()
    ]
    assert len(lines) == 5, \
        f"Expected 5 lines in dataset.jsonl, got {len(lines)}"

    for line in lines:
        record = json.loads(line)
        for key in ("sample_id", "topology", "given", "solution", "trace"):
            assert key in record, \
                f"dataset.jsonl record missing key '{key}'"
