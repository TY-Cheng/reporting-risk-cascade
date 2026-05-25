from __future__ import annotations

from pathlib import Path
from zipfile import ZipFile

import pandas as pd
import pytest

from src.raw_dataset import (
    RAW_DATASET_CSV_NAME,
    RAW_DATASET_ZIP_NAME,
    default_raw_dataset_sources,
    materialize_raw_dataset,
    resolve_raw_dataset_source,
)
from src.table_io import read_table


def test_materialize_raw_dataset_from_zip(tmp_path: Path) -> None:
    source_dir = tmp_path / "external"
    source_dir.mkdir()
    source = source_dir / "raw_dataset_misstatement.zip"
    frame = pd.DataFrame(
        {
            "gvkey": ["g001", "g002"],
            "data_year": [2020, 2021],
            "misstatement firm-year": [0, 1],
        }
    )
    csv_payload = frame.to_csv(index=False)
    with ZipFile(source, "w") as archive:
        archive.writestr("raw_dataset_misstatement.csv", csv_payload)

    out_data = tmp_path / "raw_dataset_misstatement.parquet"
    result = materialize_raw_dataset(source_path=source, out_data=out_data)

    assert result.wrote_output
    assert result.rows_written == 2
    assert result.source_path == source
    pd.testing.assert_frame_equal(read_table(out_data), frame)

    no_op = materialize_raw_dataset(source_path=source, out_data=out_data)
    assert not no_op.wrote_output
    assert no_op.rows_written == 0


def test_materialize_raw_dataset_allows_existing_output_without_source(tmp_path: Path) -> None:
    out_data = tmp_path / "raw_dataset_misstatement.parquet"
    out_data.write_bytes(b"existing parquet placeholder")

    no_op = materialize_raw_dataset(out_data=out_data)

    assert no_op.source_path is None
    assert no_op.out_data == out_data
    assert not no_op.wrote_output
    assert no_op.rows_written == 0


def test_resolve_raw_dataset_source_requires_existing_input(tmp_path: Path) -> None:
    with pytest.raises(FileNotFoundError, match="Raw benchmark source not found"):
        resolve_raw_dataset_source(tmp_path / "missing.zip")


def test_default_raw_dataset_sources_include_external_raw_subdir(tmp_path: Path) -> None:
    assert default_raw_dataset_sources(tmp_path) == (
        tmp_path / RAW_DATASET_CSV_NAME,
        tmp_path / RAW_DATASET_ZIP_NAME,
        tmp_path / "raw" / RAW_DATASET_CSV_NAME,
        tmp_path / "raw" / RAW_DATASET_ZIP_NAME,
        tmp_path / "external" / RAW_DATASET_ZIP_NAME,
    )
