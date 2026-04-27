set dotenv-load
set export
set shell := ["bash", "-euo", "pipefail", "-c"]

repo_root := justfile_directory()

default:
    @just --list

_check-env:
    @repo_root="{{ repo_root }}"; \
    test -n "${UV_PROJECT_ENVIRONMENT:-}" || { echo "UV_PROJECT_ENVIRONMENT is missing in .env"; exit 1; }; \
    case "${UV_PROJECT_ENVIRONMENT}" in \
        /*) ;; \
        *) \
            echo "UV_PROJECT_ENVIRONMENT must be an absolute path, got: ${UV_PROJECT_ENVIRONMENT}"; \
            exit 1; \
            ;; \
    esac; \
    case "${UV_PROJECT_ENVIRONMENT%/}" in \
        "$repo_root"|"$repo_root"/*) \
            echo "UV_PROJECT_ENVIRONMENT must point outside this repo, got: ${UV_PROJECT_ENVIRONMENT}"; \
            exit 1; \
            ;; \
    esac
    @test -n "${DIR_MANUSCRIPT}" || { echo "DIR_MANUSCRIPT is missing in .env"; exit 1; }
    @mkdir -p "$(dirname "${UV_PROJECT_ENVIRONMENT}")"

_ruff:
    uv run ruff check src scripts tests

_test-core:
    uv run pytest -q \
        tests/test_benchmark.py \
        tests/test_bridge.py \
        tests/test_construct_overlap.py \
        tests/test_data_prep.py \
        tests/test_docs.py \
        tests/test_peer_comparison.py \
        tests/test_public_cascade_interfaces.py \
        tests/test_public_peer_comparison.py \
        tests/test_table_io_sample.py \
        --cov=src.benchmark \
        --cov=src.bridge \
        --cov=src.construct_overlap \
        --cov=src.data_prep \
        --cov=src.peer_comparison \
        --cov=src.public_cascade \
        --cov=src.public_peer_comparison \
        --cov=src.ranking_metrics \
        --cov=src.sample_dataset \
        --cov=src.table_io \
        --cov-report=term \
        --cov-fail-under=95

_test-public-lake:
    uv run pytest -q tests/test_public_lake.py \
        --cov=src.public_lake \
        --cov-report=term \
        --cov-fail-under=93

_test: _test-core _test-public-lake

setup: _check-env
    uv sync

status: _check-env
    @echo "UV_PROJECT_ENVIRONMENT=${UV_PROJECT_ENVIRONMENT}"
    @echo "DIR_MANUSCRIPT=${DIR_MANUSCRIPT}"
    @echo "PROJECT_ROOT=${PROJECT_ROOT}"
    @echo "DATA_DIR=${DATA_DIR}"
    @echo "DOCS_DIR=${DOCS_DIR}"
    @echo "PAPER_DIR=${PAPER_DIR}"
    @echo "DIR_MANUSCRIPT=${DIR_MANUSCRIPT}"
    @if [ -x "${UV_PROJECT_ENVIRONMENT}/bin/python" ]; then \
        "${UV_PROJECT_ENVIRONMENT}/bin/python" -c "import sys; from src import PROJECT_ROOT, DATA_DIR, DOCS_DIR, PAPER_DIR, DIR_MANUSCRIPT, ARTIFACTS_DIR, RAW_DATASET_PATH, SAMPLE_DATASET_PATH; print('python_prefix', sys.prefix); print('python_project_root', PROJECT_ROOT); print('python_data_dir', DATA_DIR); print('python_docs_dir', DOCS_DIR); print('python_paper_dir', PAPER_DIR); print('python_dir_manuscript', DIR_MANUSCRIPT); print('python_artifacts_dir', ARTIFACTS_DIR); print('python_raw_dataset_path', RAW_DATASET_PATH); print('python_sample_dataset_path', SAMPLE_DATASET_PATH)"; \
    else \
        echo "python_prefix missing; run 'just setup'"; \
    fi

task name="study" dataset="raw" out_dir="" extra="": _check-env
    @task_extra="{{ extra }}"; \
    case "$task_extra" in extra=*) task_extra="${task_extra#extra=}" ;; esac; \
    case "{{ name }}" in \
        prep) \
            just _run "{{ dataset }}" "{{ out_dir }}"; \
            ;; \
        benchmark|cascade|bridge|study) \
            just _analysis "{{ name }}" "{{ dataset }}" "{{ out_dir }}" "$task_extra"; \
            ;; \
        sec-bulk|submissions|companyfacts|fsds|notes|comment-letters|aaer|form-ap|pcaob-inspections|insider|13f|edgar-logs|market-structure|build-lake) \
            just _fetch "{{ name }}" "$task_extra"; \
            ;; \
        *) \
            echo "task must be one of: prep, benchmark, cascade, bridge, study, sec-bulk, submissions, companyfacts, fsds, notes, comment-letters, aaer, form-ap, pcaob-inspections, insider, 13f, edgar-logs, market-structure, build-lake"; \
            exit 1; \
            ;; \
    esac

_run dataset="sample" out_dir="": _check-env
    @if [ "{{ dataset }}" != "sample" ] && [ "{{ dataset }}" != "raw" ]; then \
        echo "dataset must be 'sample' or 'raw'"; \
        exit 1; \
    fi
    @if [ -n "{{ out_dir }}" ]; then \
        uv run python scripts/run_data_prep.py --dataset "{{ dataset }}" --out-dir "{{ out_dir }}"; \
    else \
        uv run python scripts/run_data_prep.py --dataset "{{ dataset }}"; \
    fi

_analysis stage="study" dataset="raw" out_dir="" extra="": _check-env
    @if [ "{{ stage }}" = "benchmark" ]; then \
        if [ "{{ dataset }}" = "sample" ]; then \
            raw_data="artifacts/sample_dataset_misstatement.parquet"; \
            uv run python scripts/generate_sample_dataset.py; \
        elif [ "{{ dataset }}" = "raw" ]; then \
            raw_data="data/raw_dataset_misstatement.parquet"; \
            if [ ! -f "$raw_data" ] && [ -f "data/raw_dataset_misstatement.csv" ]; then \
                uv run python scripts/convert_raw_dataset.py; \
            fi; \
        else \
            echo "dataset must be 'sample' or 'raw'"; \
            exit 1; \
        fi; \
        if [ -n "{{ out_dir }}" ]; then \
            uv run python scripts/run_benchmark.py --raw-data "$raw_data" --out-dir "{{ out_dir }}" {{ extra }}; \
        else \
            uv run python scripts/run_benchmark.py --raw-data "$raw_data" {{ extra }}; \
        fi; \
    elif [ "{{ stage }}" = "cascade" ]; then \
        if [ -n "{{ out_dir }}" ]; then \
            uv run python scripts/run_public_cascade.py --out-dir "{{ out_dir }}" {{ extra }}; \
        else \
            uv run python scripts/run_public_cascade.py {{ extra }}; \
        fi; \
    elif [ "{{ stage }}" = "bridge" ]; then \
        if [ "{{ dataset }}" = "sample" ]; then \
            raw_data="artifacts/sample_dataset_misstatement.parquet"; \
            uv run python scripts/generate_sample_dataset.py; \
        elif [ "{{ dataset }}" = "raw" ]; then \
            raw_data="data/raw_dataset_misstatement.parquet"; \
            if [ ! -f "$raw_data" ] && [ -f "data/raw_dataset_misstatement.csv" ]; then \
                uv run python scripts/convert_raw_dataset.py; \
            fi; \
        else \
            echo "dataset must be 'sample' or 'raw'"; \
            exit 1; \
        fi; \
        if [ -n "{{ out_dir }}" ]; then \
            uv run python scripts/run_bridge_probe.py --raw-data "$raw_data" --out-dir "{{ out_dir }}" {{ extra }}; \
        else \
            uv run python scripts/run_bridge_probe.py --raw-data "$raw_data" {{ extra }}; \
        fi; \
    elif [ "{{ stage }}" = "study" ]; then \
        if [ "{{ dataset }}" = "sample" ]; then \
            raw_data="artifacts/sample_dataset_misstatement.parquet"; \
            uv run python scripts/generate_sample_dataset.py; \
        elif [ "{{ dataset }}" = "raw" ]; then \
            raw_data="data/raw_dataset_misstatement.parquet"; \
            if [ ! -f "$raw_data" ] && [ -f "data/raw_dataset_misstatement.csv" ]; then \
                uv run python scripts/convert_raw_dataset.py; \
            fi; \
        else \
            echo "dataset must be 'sample' or 'raw'"; \
            exit 1; \
        fi; \
        if [ -n "{{ out_dir }}" ]; then \
            uv run python scripts/run_study.py --raw-data "$raw_data" --out-dir "{{ out_dir }}" {{ extra }}; \
        else \
            uv run python scripts/run_study.py --raw-data "$raw_data" {{ extra }}; \
        fi; \
    else \
        echo "stage must be 'study', 'benchmark', 'cascade', or 'bridge'"; \
        exit 1; \
    fi

_fetch source="sec-bulk" extra="": _check-env
    uv run python scripts/fetch_public_data.py --mode "{{ source }}" {{ extra }}

full *args: _check-env
    @mode="smoke"; dataset="sample"; out_dir=""; as_of_date="2026-04-23"; fetch_workers="2"; model_jobs="4"; model_threads="2"; engine="duckdb"; storage_format="parquet"; notes_mode="summary"; fresh_build="0"; force_fetch="0"; resume="0"; duckdb_memory_limit="10GB"; duckdb_temp_directory=""; duckdb_max_temp_size="400GB"; fsds_batch_size="4"; notes_batch_size="2"; pos=1; \
    for arg in {{ args }}; do \
        case "$arg" in \
            mode=*) mode="${arg#mode=}" ;; \
            dataset=*) dataset="${arg#dataset=}" ;; \
            out_dir=*) out_dir="${arg#out_dir=}" ;; \
            as_of_date=*) as_of_date="${arg#as_of_date=}" ;; \
            fetch_workers=*) fetch_workers="${arg#fetch_workers=}" ;; \
            model_jobs=*) model_jobs="${arg#model_jobs=}" ;; \
            model_threads=*) model_threads="${arg#model_threads=}" ;; \
            engine=*) engine="${arg#engine=}" ;; \
            storage_format=*) storage_format="${arg#storage_format=}" ;; \
            notes_mode=*) notes_mode="${arg#notes_mode=}" ;; \
            fresh_build=*) fresh_build="${arg#fresh_build=}" ;; \
            force_fetch=*) force_fetch="${arg#force_fetch=}" ;; \
            resume=*) resume="${arg#resume=}" ;; \
            duckdb_memory_limit=*) duckdb_memory_limit="${arg#duckdb_memory_limit=}" ;; \
            duckdb_temp_directory=*) duckdb_temp_directory="${arg#duckdb_temp_directory=}" ;; \
            duckdb_max_temp_size=*) duckdb_max_temp_size="${arg#duckdb_max_temp_size=}" ;; \
            fsds_batch_size=*) fsds_batch_size="${arg#fsds_batch_size=}" ;; \
            notes_batch_size=*) notes_batch_size="${arg#notes_batch_size=}" ;; \
            *=*) echo "Unknown full option: $arg"; exit 2 ;; \
            *) \
                case "$pos" in \
                    1) mode="$arg" ;; \
                    2) dataset="$arg" ;; \
                    3) out_dir="$arg" ;; \
                    4) as_of_date="$arg" ;; \
                    5) fetch_workers="$arg" ;; \
                    6) model_jobs="$arg" ;; \
                    7) model_threads="$arg" ;; \
                    8) engine="$arg" ;; \
                    9) storage_format="$arg" ;; \
                    10) notes_mode="$arg" ;; \
                    11) fresh_build="$arg" ;; \
                    12) force_fetch="$arg" ;; \
                    13) duckdb_memory_limit="$arg" ;; \
                    14) duckdb_temp_directory="$arg" ;; \
                    15) duckdb_max_temp_size="$arg" ;; \
                    16) fsds_batch_size="$arg" ;; \
                    17) notes_batch_size="$arg" ;; \
                    *) echo "Too many full positional arguments: $arg"; exit 2 ;; \
                esac; \
                pos=$((pos + 1)); \
                ;; \
        esac; \
    done; \
    if [ "$mode" != "smoke" ] && [ "$mode" != "full" ]; then \
        echo "mode must be 'smoke' or 'full'"; \
        exit 1; \
    fi; \
    if [ "$dataset" != "sample" ] && [ "$dataset" != "raw" ]; then \
        echo "dataset must be 'sample' or 'raw'"; \
        exit 1; \
    fi; \
    if [ "$engine" != "pandas" ] && [ "$engine" != "duckdb" ]; then \
        echo "engine must be 'pandas' or 'duckdb'"; \
        exit 1; \
    fi; \
    if [ "$storage_format" != "parquet" ] && [ "$storage_format" != "csv-gz" ]; then \
        echo "storage_format must be 'parquet' or 'csv-gz'"; \
        exit 1; \
    fi; \
    if [ "$notes_mode" != "summary" ] && [ "$notes_mode" != "raw" ] && [ "$notes_mode" != "skip" ]; then \
        echo "notes_mode must be 'summary', 'raw', or 'skip'"; \
        exit 1; \
    fi; \
    if [ "$storage_format" = "parquet" ] && [ "$engine" != "duckdb" ]; then \
        echo "storage_format=parquet requires engine=duckdb"; \
        exit 1; \
    fi; \
    for numeric_arg in "$fetch_workers" "$model_jobs" "$model_threads" "$fsds_batch_size" "$notes_batch_size"; do \
        case "$numeric_arg" in ''|*[!0-9]*) echo "fetch_workers, model_jobs, model_threads, fsds_batch_size, and notes_batch_size must be positive integers"; exit 1 ;; esac; \
        if [ "$numeric_arg" -lt 1 ]; then echo "fetch_workers, model_jobs, model_threads, fsds_batch_size, and notes_batch_size must be positive integers"; exit 1; fi; \
    done; \
    just setup; \
    just _test; \
    just _ruff; \
    if [ ! -f "data/raw_dataset_misstatement.parquet" ] && [ -f "data/raw_dataset_misstatement.csv" ]; then \
        uv run python scripts/convert_raw_dataset.py; \
    fi; \
    if [ "$dataset" = "raw" ] && [ ! -f "data/raw_dataset_misstatement.parquet" ]; then \
        echo "data/raw_dataset_misstatement.parquet is required for dataset=raw"; \
        echo "If only the legacy CSV exists, run: uv run python scripts/convert_raw_dataset.py"; \
        exit 1; \
    fi; \
    run_out="$out_dir"; \
    if [ -z "$run_out" ]; then \
        run_out="artifacts/full_${mode}_${dataset}"; \
    fi; \
    if [ "$dataset" = "sample" ]; then \
        uv run python scripts/generate_sample_dataset.py; \
        raw_data="artifacts/sample_dataset_misstatement.parquet"; \
    else \
        raw_data="data/raw_dataset_misstatement.parquet"; \
    fi; \
    if [ "$mode" = "smoke" ]; then \
        silver_dir="data/public_lake_smoke/silver"; \
        gold_dir="data/public_lake_smoke/gold"; \
    else \
        silver_dir="data/public_lake/silver"; \
        gold_dir="data/public_lake/gold"; \
    fi; \
    if [ "$engine" = "duckdb" ] && [ -z "$duckdb_temp_directory" ]; then \
        duckdb_temp_directory="$silver_dir/._duckdb_tmp"; \
    fi; \
    lake_args=""; \
    if [ "$fresh_build" = "1" ] || [ "$fresh_build" = "true" ]; then lake_args="$lake_args --fresh-build"; fi; \
    if [ "$force_fetch" = "1" ] || [ "$force_fetch" = "true" ]; then lake_args="$lake_args --force"; fi; \
    if [ "$resume" = "1" ] || [ "$resume" = "true" ]; then lake_args="$lake_args --resume"; fi; \
    bash scripts/run_public_lake_full.sh \
        --mode "$mode" \
        --as-of-date "$as_of_date" \
        --fetch-workers "$fetch_workers" \
        --engine "$engine" \
        --duckdb-threads "$model_threads" \
        --duckdb-memory-limit "$duckdb_memory_limit" \
        --duckdb-max-temp-size "$duckdb_max_temp_size" \
        --storage-format "$storage_format" \
        --notes-mode "$notes_mode" \
        --fsds-batch-size "$fsds_batch_size" \
        --notes-batch-size "$notes_batch_size" \
        --skip-setup \
        --skip-public-cascade ${duckdb_temp_directory:+--duckdb-temp-directory "$duckdb_temp_directory"} $lake_args; \
    uv run python scripts/run_study.py \
        --raw-data "$raw_data" \
        --issuer-dim "$silver_dir/issuer_dim.parquet" \
        --issuer-origin-panel "$gold_dir/issuer_origin_panel.parquet" \
        --out-dir "$run_out" \
        --parallel-jobs "$model_jobs" \
        --model-threads "$model_threads" \
        --seed-policy task-isolated; \
    echo "Full workflow outputs: $run_out"

check: _check-env
    just _test
    just _ruff
    just _docs-build

docs: _docs-build
    @for port in 8001 8002 8003 8004 8005 8006 8007 8008 8009 8010; do \
        if ! lsof -nP -iTCP:${port} -sTCP:LISTEN >/dev/null 2>&1; then \
            echo "Serving docs on http://127.0.0.1:${port}"; \
            uv run --group docs mkdocs serve --clean -a "127.0.0.1:${port}"; \
            exit 0; \
        fi; \
    done; \
    echo "No free docs port in 8001-8010"; \
    exit 1

_docs-build: _check-env
    uv run --group docs mkdocs build --strict --clean
