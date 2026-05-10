from __future__ import annotations

import random
from dataclasses import dataclass
from pathlib import Path

from . import SEED_DEFAULT
from .table_io import read_table, write_table


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

    raw = read_table(raw_csv, low_memory=False)
    if firm_col not in raw.columns:
        raise ValueError(f"Expected '{firm_col}' in {raw_csv}")

    unique_firms = sorted(raw[firm_col].dropna().astype(str).unique().tolist())

    if n_firms > len(unique_firms):
        raise ValueError(f"Requested {n_firms} firms, but only found {len(unique_firms)}")

    selected_firms = set(random.Random(seed).sample(unique_firms, n_firms))

    sample = raw.loc[raw[firm_col].astype(str).isin(selected_firms)].copy()
    write_table(sample, out_csv)

    return SampleDatasetSummary(
        out_csv=out_csv,
        n_firms=n_firms,
        rows_written=int(len(sample)),
        seed=seed,
    )
