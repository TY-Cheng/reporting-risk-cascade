from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from zipfile import ZipFile

import pandas as pd

from . import DATA_DIR, RAW_DATASET_PATH
from .table_io import read_table, write_table

RAW_DATASET_CSV_NAME = "raw_dataset_misstatement.csv"
RAW_DATASET_ZIP_NAME = "raw_dataset_misstatement.zip"


@dataclass(frozen=True)
class RawDatasetMaterialization:
    source_path: Path | None
    out_data: Path
    rows_written: int
    wrote_output: bool


def default_raw_dataset_sources(data_dir: Path = DATA_DIR) -> tuple[Path, ...]:
    return (
        data_dir / RAW_DATASET_CSV_NAME,
        data_dir / RAW_DATASET_ZIP_NAME,
        data_dir / "raw" / RAW_DATASET_CSV_NAME,
        data_dir / "raw" / RAW_DATASET_ZIP_NAME,
    )


def resolve_raw_dataset_source(source_path: Path | None = None) -> Path:
    if source_path is not None:
        source = source_path.expanduser()
        if not source.exists():
            raise FileNotFoundError(f"Raw benchmark source not found: {source}")
        return source

    for candidate in default_raw_dataset_sources():
        if candidate.exists():
            return candidate

    candidates = ", ".join(str(path) for path in default_raw_dataset_sources())
    raise FileNotFoundError(
        "Raw benchmark source not found. Expected one of: " + candidates
    )


def _zip_csv_member(path: Path) -> str:
    with ZipFile(path) as archive:
        csv_members = [
            name
            for name in archive.namelist()
            if not name.endswith("/") and Path(name).suffix.lower() == ".csv"
        ]
    if RAW_DATASET_CSV_NAME in csv_members:
        return RAW_DATASET_CSV_NAME
    if len(csv_members) == 1:
        return csv_members[0]
    raise ValueError(
        f"Expected exactly one raw CSV in {path}; found {len(csv_members)} CSV members"
    )


def read_raw_dataset_source(path: Path) -> pd.DataFrame:
    path = path.expanduser()
    if path.suffix.lower() != ".zip":
        return read_table(path, low_memory=False)

    member = _zip_csv_member(path)
    with ZipFile(path) as archive:
        with archive.open(member) as handle:
            return pd.read_csv(handle, low_memory=False)


def materialize_raw_dataset(
    *,
    source_path: Path | None = None,
    out_data: Path = RAW_DATASET_PATH,
    overwrite: bool = False,
) -> RawDatasetMaterialization:
    out_data = out_data.expanduser()
    if out_data.exists() and not overwrite:
        source = resolve_raw_dataset_source(source_path) if source_path is not None else None
        return RawDatasetMaterialization(
            source_path=source,
            out_data=out_data,
            rows_written=0,
            wrote_output=False,
        )

    source = resolve_raw_dataset_source(source_path)
    frame = read_raw_dataset_source(source)
    write_table(frame, out_data, overwrite=True)
    return RawDatasetMaterialization(
        source_path=source,
        out_data=out_data,
        rows_written=int(len(frame)),
        wrote_output=True,
    )
