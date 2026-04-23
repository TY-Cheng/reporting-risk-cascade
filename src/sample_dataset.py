from __future__ import annotations

import csv
import random
from dataclasses import dataclass
from pathlib import Path

from . import SEED_DEFAULT


@dataclass(frozen=True)
class SampleDatasetSummary:
    out_csv: Path
    n_firms: int
    rows_written: int
    seed: int


def materialize_sample_dataset(
    raw_csv: Path,
    out_csv: Path,
    *,
    firm_col: str = "gvkey",
    n_firms: int = 500,
    seed: int = SEED_DEFAULT,
) -> SampleDatasetSummary:
    if n_firms <= 0:
        raise ValueError("n_firms must be positive")

    with raw_csv.open(newline="", encoding="utf-8") as handle:
        reader = csv.DictReader(handle)
        fieldnames = reader.fieldnames
        if fieldnames is None or firm_col not in fieldnames:
            raise ValueError(f"Expected '{firm_col}' in {raw_csv}")

        unique_firms = sorted({row[firm_col] for row in reader})

    if n_firms > len(unique_firms):
        raise ValueError(f"Requested {n_firms} firms, but only found {len(unique_firms)}")

    selected_firms = set(random.Random(seed).sample(unique_firms, n_firms))

    out_csv.parent.mkdir(parents=True, exist_ok=True)
    rows_written = 0

    with (
        raw_csv.open(newline="", encoding="utf-8") as src_handle,
        out_csv.open("w", newline="", encoding="utf-8") as out_handle,
    ):
        reader = csv.DictReader(src_handle)
        writer = csv.DictWriter(out_handle, fieldnames=reader.fieldnames)
        writer.writeheader()

        for row in reader:
            if row[firm_col] in selected_firms:
                writer.writerow(row)
                rows_written += 1

    return SampleDatasetSummary(
        out_csv=out_csv,
        n_firms=n_firms,
        rows_written=rows_written,
        seed=seed,
    )
