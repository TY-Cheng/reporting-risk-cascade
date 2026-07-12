"""
Small table I/O helpers for CSV and Parquet datasets.

Parquet reads and writes go through DuckDB so the project does not need a
separate pyarrow dependency for its storage migration.
"""

from __future__ import annotations

import shutil
from pathlib import Path
from typing import Any, Sequence

import pandas as pd


def _require_duckdb() -> Any:
    try:
        import duckdb
    except ImportError as exc:  # pragma: no cover - dependency guard
        raise RuntimeError("DuckDB is required for Parquet table I/O.") from exc
    return duckdb


def _duckdb_path(path: Path) -> str:
    return str(path).replace("'", "''")


def _duckdb_identifier(name: str) -> str:
    return '"' + str(name).replace('"', '""') + '"'


def _duckdb_path_list(paths: Sequence[Path]) -> str:
    return "[" + ", ".join(f"'{_duckdb_path(path)}'" for path in paths) + "]"


DEFAULT_DUCKDB_MEMORY_LIMIT = "10GB"
DEFAULT_DUCKDB_MAX_TEMP_DIRECTORY_SIZE = "400GB"


def _duckdb_literal(value: str | Path) -> str:
    return "'" + str(value).replace("'", "''") + "'"


def _connect(
    *,
    threads: int = 4,
    memory_limit: str | None = DEFAULT_DUCKDB_MEMORY_LIMIT,
    temp_directory: Path | str | None = None,
    max_temp_directory_size: str | None = DEFAULT_DUCKDB_MAX_TEMP_DIRECTORY_SIZE,
) -> Any:
    duckdb = _require_duckdb()
    con = duckdb.connect(database=":memory:")
    con.execute(f"PRAGMA threads={max(1, int(threads))}")
    con.execute("SET preserve_insertion_order = false")
    if memory_limit:
        con.execute(f"SET memory_limit = {_duckdb_literal(memory_limit)}")
    if temp_directory:
        Path(temp_directory).mkdir(parents=True, exist_ok=True)
        con.execute(f"SET temp_directory = {_duckdb_literal(temp_directory)}")
    if max_temp_directory_size:
        con.execute(f"SET max_temp_directory_size = {_duckdb_literal(max_temp_directory_size)}")
    return con


def is_parquet_path(path: Path) -> bool:
    return path.suffix.lower() == ".parquet" or path.is_dir()


def parquet_scan_sql(path: Path) -> str:
    if path.is_dir():
        files = sorted(path.rglob("*.parquet"))
        if not files:
            raise FileNotFoundError(f"No Parquet files found under {path}")
        return f"read_parquet({_duckdb_path_list(files)}, hive_partitioning=true)"
    return f"read_parquet('{_duckdb_path(path)}')"


def read_table(
    path: Path,
    *,
    columns: Sequence[str] | None = None,
    date_cols: Sequence[str] = (),
    duckdb_threads: int = 4,
    duckdb_memory_limit: str | None = DEFAULT_DUCKDB_MEMORY_LIMIT,
    duckdb_temp_directory: Path | str | None = None,
    duckdb_max_temp_directory_size: str | None = DEFAULT_DUCKDB_MAX_TEMP_DIRECTORY_SIZE,
    low_memory: bool = False,
) -> pd.DataFrame:
    path = Path(path)
    if is_parquet_path(path):
        select_expr = "*"
        if columns is not None:
            select_expr = ", ".join(_duckdb_identifier(col) for col in columns)
        con = _connect(
            threads=duckdb_threads,
            memory_limit=duckdb_memory_limit,
            temp_directory=duckdb_temp_directory,
            max_temp_directory_size=duckdb_max_temp_directory_size,
        )
        try:
            frame = con.execute(f"SELECT {select_expr} FROM {parquet_scan_sql(path)}").fetchdf()
        finally:
            con.close()
    else:
        read_kwargs: dict[str, Any] = {"low_memory": low_memory}
        if columns is not None:
            read_kwargs["usecols"] = list(columns)
        frame = pd.read_csv(path, **read_kwargs)

    for col in date_cols:
        if col in frame.columns:
            frame[col] = pd.to_datetime(frame[col], errors="coerce", format="mixed")
    return frame


def write_table(
    frame: pd.DataFrame,
    path: Path,
    *,
    duckdb_threads: int = 4,
    duckdb_memory_limit: str | None = DEFAULT_DUCKDB_MEMORY_LIMIT,
    duckdb_temp_directory: Path | str | None = None,
    duckdb_max_temp_directory_size: str | None = DEFAULT_DUCKDB_MAX_TEMP_DIRECTORY_SIZE,
    overwrite: bool = True,
    preserve_order: bool = False,
) -> Path:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.suffix.lower() == ".parquet":
        if path.exists():
            if not overwrite:
                raise FileExistsError(path)
            path.unlink()
        con = _connect(
            threads=1 if preserve_order else duckdb_threads,
            memory_limit=duckdb_memory_limit,
            temp_directory=duckdb_temp_directory,
            max_temp_directory_size=duckdb_max_temp_directory_size,
        )
        try:
            con.register("_table_io_frame", frame)
            options = ["FORMAT PARQUET", "COMPRESSION ZSTD"]
            if preserve_order:
                options.append("PRESERVE_ORDER true")
            con.execute(
                f"""
                COPY _table_io_frame
                TO '{_duckdb_path(path)}'
                ({", ".join(options)})
                """
            )
        finally:
            con.close()
        return path

    if path.exists() and not overwrite:
        raise FileExistsError(path)
    compression = "gzip" if path.suffix.lower() == ".gz" else None
    frame.to_csv(path, index=False, compression=compression)
    return path


def remove_table_path(path: Path) -> None:
    path = Path(path)
    if path.is_dir():
        shutil.rmtree(path)
    elif path.exists():
        path.unlink()
