from __future__ import annotations

import hashlib
from pathlib import Path
import tomllib

import pandas as pd
import pytest

from src.sample_dataset import materialize_sample_dataset
from src.table_io import parquet_scan_sql, read_table, remove_table_path, write_table


def test_project_requires_duckdb_with_preserve_order_copy_support() -> None:
    project = tomllib.loads((Path(__file__).parents[1] / "pyproject.toml").read_text())
    assert "duckdb>=1.3.2,<2" in project["project"]["dependencies"]


def test_write_table_preserve_order_is_byte_stable_across_thread_settings(
    tmp_path: Path,
) -> None:
    frame = pd.DataFrame(
        {
            "issuer_cik": [f"{value:010d}" for value in range(1_000)],
            "fiscal_year": [2020 + (value % 5) for value in range(1_000)],
            "accession": [f"accession-{value:04d}" for value in range(1_000)],
        }
    )
    thread1 = tmp_path / "thread1.parquet"
    thread4 = tmp_path / "thread4.parquet"

    write_table(frame, thread1, duckdb_threads=1, preserve_order=True)
    write_table(frame, thread4, duckdb_threads=4, preserve_order=True)

    pd.testing.assert_frame_equal(read_table(thread1), frame)
    assert (
        hashlib.sha256(thread1.read_bytes()).hexdigest()
        == hashlib.sha256(thread4.read_bytes()).hexdigest()
    )


def test_table_io_csv_parquet_directory_projection_dates_and_overwrite(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    frame = pd.DataFrame(
        {
            "firm": ["a", "b", "c"],
            "date": ["2020-01-01", "2020-01-02", "2020-01-03"],
            "value": [1, 2, 3],
        }
    )
    csv_path = tmp_path / "first" / "table.csv.gz"
    csv_copy = tmp_path / "second" / "table.csv.gz"
    parquet_path = tmp_path / "table.parquet"
    monkeypatch.setattr("gzip.time.time", lambda: 1_700_000_000.0)
    write_table(frame, csv_path)
    monkeypatch.setattr("gzip.time.time", lambda: 1_800_000_000.0)
    write_table(frame, csv_copy)
    write_table(frame, parquet_path)
    assert csv_path.read_bytes() == csv_copy.read_bytes()
    with pytest.raises(FileExistsError):
        write_table(frame, parquet_path, overwrite=False)
    with pytest.raises(FileExistsError):
        write_table(frame, csv_path, overwrite=False)

    csv_loaded = read_table(csv_path, columns=["firm", "date"], date_cols=["date"])
    parquet_loaded = read_table(parquet_path, columns=["firm", "date"], date_cols=["date"])
    assert csv_loaded["date"].dt.year.tolist() == [2020, 2020, 2020]
    pd.testing.assert_frame_equal(csv_loaded, parquet_loaded)

    dataset_dir = tmp_path / "dataset"
    write_table(frame.iloc[:1], dataset_dir / "part_a.parquet")
    write_table(frame.iloc[1:], dataset_dir / "nested" / "part_b.parquet")
    assert "read_parquet" in parquet_scan_sql(dataset_dir)
    assert len(read_table(dataset_dir)) == 3
    (tmp_path / "empty_dataset").mkdir()
    with pytest.raises(FileNotFoundError):
        parquet_scan_sql(tmp_path / "empty_dataset")

    remove_table_path(dataset_dir)
    remove_table_path(csv_path)
    assert not dataset_dir.exists()
    assert not csv_path.exists()


def test_sample_dataset_materialization_rejects_missing_firm_key(tmp_path: Path) -> None:
    raw_path = tmp_path / "raw.csv"
    out_path = tmp_path / "sample.parquet"
    pd.DataFrame({"data_year": [2020], "misstatement firm-year": [0]}).to_csv(
        raw_path, index=False
    )
    with pytest.raises(ValueError, match="Expected 'gvkey'"):
        materialize_sample_dataset(raw_path, out_path, n_firms=1)
    with pytest.raises(ValueError, match="n_firms must be positive"):
        materialize_sample_dataset(raw_path, out_path, n_firms=0)


def test_sample_dataset_materialization_rejects_too_many_firms(tmp_path: Path) -> None:
    raw_path = tmp_path / "raw.csv"
    out_path = tmp_path / "sample.parquet"
    pd.DataFrame(
        {
            "gvkey": ["a"],
            "data_year": [2020],
            "misstatement firm-year": [0],
        }
    ).to_csv(raw_path, index=False)
    with pytest.raises(ValueError, match="Requested 2 firms"):
        materialize_sample_dataset(raw_path, out_path, n_firms=2)
