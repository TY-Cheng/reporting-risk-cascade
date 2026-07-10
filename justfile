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
	repo_root_real="$(python3 -c 'from pathlib import Path; import sys; print(Path(sys.argv[1]).resolve())' "$repo_root")"; \
	uv_env_real="$(python3 -c 'from pathlib import Path; import sys; print(Path(sys.argv[1]).resolve())' "$UV_PROJECT_ENVIRONMENT")"; \
	case "$uv_env_real" in \
		"$repo_root_real"|"$repo_root_real"/*) \
			echo "UV_PROJECT_ENVIRONMENT must point outside this repo, got: ${UV_PROJECT_ENVIRONMENT}"; \
			exit 1; \
			;; \
	esac
	@mkdir -p "$(dirname "${UV_PROJECT_ENVIRONMENT}")"

_check-data-env: _check-env
	@repo_root="{{ repo_root }}"; \
	test -n "${DATA_DIR:-}" || { echo "DATA_DIR is missing in .env"; exit 1; }; \
	test -n "${ARTIFACTS_DIR:-}" || { echo "ARTIFACTS_DIR is missing in .env"; exit 1; }; \
	repo_root_real="$(python3 -c 'from pathlib import Path; import sys; print(Path(sys.argv[1]).resolve())' "$repo_root")"; \
	public_lake_dir="${PUBLIC_LAKE_DIR:-${DATA_DIR}/public_lake}"; \
	public_lake_smoke_dir="${PUBLIC_LAKE_SMOKE_DIR:-${DATA_DIR}/public_lake_smoke}"; \
	for data_path in \
		"$DATA_DIR" \
		"$public_lake_dir" \
		"$public_lake_smoke_dir" \
		"${LAKE_BRONZE_DIR:-${public_lake_dir}/bronze}" \
		"${LAKE_SILVER_DIR:-${public_lake_dir}/silver}" \
		"${LAKE_GOLD_DIR:-${public_lake_dir}/gold}"; do \
		case "$data_path" in \
			/*) ;; \
			*) echo "data paths must be absolute, got: $data_path"; exit 1 ;; \
		esac; \
		data_path_real="$(python3 -c 'from pathlib import Path; import sys; print(Path(sys.argv[1]).resolve())' "$data_path")"; \
		case "$data_path_real" in \
			"$repo_root_real"|"$repo_root_real"/*) \
				echo "data paths must point outside this repo, got: $data_path"; \
				exit 1; \
				;; \
		esac; \
	done
	@repo_root="{{ repo_root }}"; \
	case "${ARTIFACTS_DIR}" in \
		/*) ;; \
		*) echo "ARTIFACTS_DIR must be an absolute path, got: ${ARTIFACTS_DIR}"; exit 1 ;; \
	esac

_ruff:
    uv run ruff check src scripts tests

_test-core:
    uv run pytest -q \
        tests/test_benchmark.py \
        tests/test_bridge.py \
        tests/test_construct_overlap.py \
        tests/test_data_prep.py \
        tests/test_docs.py \
        tests/test_manuscript_package.py \
        tests/test_peer_comparison.py \
        tests/test_public_cascade_interfaces.py \
        tests/test_public_peer_comparison.py \
        tests/test_provenance.py \
        tests/test_repo_hygiene.py \
        tests/test_linkage.py \
        tests/test_raw_dataset.py \
        tests/test_table_io_sample.py \
        --cov=src.benchmark \
        --cov=src.bridge \
        --cov=src.construct_overlap \
        --cov=src.data_prep \
        --cov=src.linkage \
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

status: _check-data-env
    @echo "UV_PROJECT_ENVIRONMENT=${UV_PROJECT_ENVIRONMENT}"
    @echo "MANUSCRIPT_DIR=${MANUSCRIPT_DIR:-${DIR_MANUSCRIPT:-}}"
    @echo "PROJECT_ROOT=${PROJECT_ROOT}"
    @echo "WORK_DIR=${WORK_DIR:-${DIR_WORK:-${PROJECT_ROOT}}}"
    @echo "DATA_DIR=${DATA_DIR}"
    @echo "DOCS_DIR=${DOCS_DIR}"
    @echo "PAPER_DIR=${PAPER_DIR}"
    @echo "ARTIFACTS_DIR=${ARTIFACTS_DIR}"
    @echo "PUBLIC_LAKE_DIR=${PUBLIC_LAKE_DIR:-${DATA_DIR}/public_lake}"
    @echo "PUBLIC_LAKE_SMOKE_DIR=${PUBLIC_LAKE_SMOKE_DIR:-${DATA_DIR}/public_lake_smoke}"
    @echo "LAKE_BRONZE_DIR=${LAKE_BRONZE_DIR:-${PUBLIC_LAKE_DIR:-${DATA_DIR}/public_lake}/bronze}"
    @echo "LAKE_SILVER_DIR=${LAKE_SILVER_DIR:-${PUBLIC_LAKE_DIR:-${DATA_DIR}/public_lake}/silver}"
    @echo "LAKE_GOLD_DIR=${LAKE_GOLD_DIR:-${PUBLIC_LAKE_DIR:-${DATA_DIR}/public_lake}/gold}"
    @echo "RAW_DATASET_PATH=${RAW_DATASET_PATH:-${DATA_DIR}/raw/raw_dataset_misstatement.parquet}"
    @echo "MANUSCRIPT_DIR=${MANUSCRIPT_DIR:-${DIR_MANUSCRIPT:-}}"
    @if [ -x "${UV_PROJECT_ENVIRONMENT}/bin/python" ]; then \
        "${UV_PROJECT_ENVIRONMENT}/bin/python" -c "import sys; from src import PROJECT_ROOT, WORK_DIR, DATA_DIR, DOCS_DIR, PAPER_DIR, MANUSCRIPT_DIR, ARTIFACTS_DIR, PUBLIC_LAKE_DIR, PUBLIC_LAKE_SMOKE_DIR, LAKE_BRONZE_DIR, LAKE_SILVER_DIR, LAKE_GOLD_DIR, RAW_DATASET_PATH, SAMPLE_DATASET_PATH; print('python_prefix', sys.prefix); print('python_project_root', PROJECT_ROOT); print('python_work_dir', WORK_DIR); print('python_data_dir', DATA_DIR); print('python_docs_dir', DOCS_DIR); print('python_paper_dir', PAPER_DIR); print('python_manuscript_dir', MANUSCRIPT_DIR); print('python_artifacts_dir', ARTIFACTS_DIR); print('python_public_lake_dir', PUBLIC_LAKE_DIR); print('python_public_lake_smoke_dir', PUBLIC_LAKE_SMOKE_DIR); print('python_lake_bronze_dir', LAKE_BRONZE_DIR); print('python_lake_silver_dir', LAKE_SILVER_DIR); print('python_lake_gold_dir', LAKE_GOLD_DIR); print('python_raw_dataset_path', RAW_DATASET_PATH); print('python_sample_dataset_path', SAMPLE_DATASET_PATH)"; \
    else \
        echo "python_prefix missing; run 'just setup'"; \
    fi

task name="study" dataset="raw" out_dir="" extra="": _check-data-env
    @task_extra="{{ extra }}"; \
    case "$task_extra" in extra=*) task_extra="${task_extra#extra=}" ;; esac; \
    case "{{ name }}" in \
        prep) \
            just _run "{{ dataset }}" "{{ out_dir }}"; \
            ;; \
        benchmark|cascade|bridge|study) \
            just _analysis "{{ name }}" "{{ dataset }}" "{{ out_dir }}" "$task_extra"; \
            ;; \
        sec-bulk|fsds|notes|comment-letters|form-ap|pcaob-inspections|insider|13f|edgar-logs|market-structure|build-lake) \
            just _fetch "{{ name }}" "$task_extra"; \
            ;; \
        *) \
            echo "task must be one of: prep, benchmark, cascade, bridge, study, sec-bulk, fsds, notes, comment-letters, form-ap, pcaob-inspections, insider, 13f, edgar-logs, market-structure, build-lake"; \
            exit 1; \
            ;; \
    esac

_run dataset="sample" out_dir="": _check-data-env
    @out_dir_arg="{{ out_dir }}"; \
    if [ -n "$out_dir_arg" ]; then \
        case "$out_dir_arg" in \
            /*) \
                case "$out_dir_arg" in \
                    "${ARTIFACTS_DIR}"|"${ARTIFACTS_DIR}"/*|"{{ repo_root }}"|"{{ repo_root }}"/*|/tmp/*) ;; \
                    *) \
                        echo "out_dir must be relative or under ARTIFACTS_DIR; got: $out_dir_arg"; \
                        echo "If this came from an unset shell variable, use a repo-relative path like artifacts/full_with_peer."; \
                        exit 1; \
                        ;; \
                esac; \
                ;; \
        esac; \
    fi; \
    if [ "{{ dataset }}" != "sample" ] && [ "{{ dataset }}" != "raw" ]; then \
        echo "dataset must be 'sample' or 'raw'"; \
        exit 1; \
    fi
    @out_dir_arg="{{ out_dir }}"; \
    if [ -n "$out_dir_arg" ]; then \
        uv run python scripts/run_data_prep.py --dataset "{{ dataset }}" --out-dir "$out_dir_arg"; \
    else \
        uv run python scripts/run_data_prep.py --dataset "{{ dataset }}"; \
    fi

_analysis stage="study" dataset="raw" out_dir="" extra="": _check-data-env
    @raw_dataset_path="${RAW_DATASET_PATH:-${DATA_DIR}/raw/raw_dataset_misstatement.parquet}"; \
    sample_dataset_path="${SAMPLE_DATASET_PATH:-${ARTIFACTS_DIR}/sample_dataset_misstatement.parquet}"; \
    out_dir_arg="{{ out_dir }}"; \
    if [ -n "$out_dir_arg" ]; then \
        case "$out_dir_arg" in \
            /*) \
                case "$out_dir_arg" in \
                    "${ARTIFACTS_DIR}"|"${ARTIFACTS_DIR}"/*|"{{ repo_root }}"|"{{ repo_root }}"/*|/tmp/*) ;; \
                    *) \
                        echo "out_dir must be relative or under ARTIFACTS_DIR; got: $out_dir_arg"; \
                        echo "If this came from an unset shell variable, use a repo-relative path like artifacts/full_with_peer."; \
                        exit 1; \
                        ;; \
                esac; \
                ;; \
        esac; \
    fi; \
    if [ "{{ stage }}" = "benchmark" ]; then \
        if [ "{{ dataset }}" = "sample" ]; then \
            raw_data="$sample_dataset_path"; \
            uv run python scripts/generate_sample_dataset.py; \
        elif [ "{{ dataset }}" = "raw" ]; then \
            raw_data="$raw_dataset_path"; \
            if [ ! -f "$raw_data" ]; then \
                uv run python scripts/convert_raw_dataset.py; \
            fi; \
        else \
            echo "dataset must be 'sample' or 'raw'"; \
            exit 1; \
        fi; \
        if [ -n "$out_dir_arg" ]; then \
            uv run python scripts/run_benchmark.py --raw-data "$raw_data" --out-dir "$out_dir_arg" {{ extra }}; \
        else \
            uv run python scripts/run_benchmark.py --raw-data "$raw_data" {{ extra }}; \
        fi; \
    elif [ "{{ stage }}" = "cascade" ]; then \
        if [ -n "$out_dir_arg" ]; then \
            uv run python scripts/run_public_cascade.py --out-dir "$out_dir_arg" {{ extra }}; \
        else \
            uv run python scripts/run_public_cascade.py {{ extra }}; \
        fi; \
    elif [ "{{ stage }}" = "bridge" ]; then \
        if [ "{{ dataset }}" = "sample" ]; then \
            raw_data="$sample_dataset_path"; \
            uv run python scripts/generate_sample_dataset.py; \
        elif [ "{{ dataset }}" = "raw" ]; then \
            raw_data="$raw_dataset_path"; \
            if [ ! -f "$raw_data" ]; then \
                uv run python scripts/convert_raw_dataset.py; \
            fi; \
        else \
            echo "dataset must be 'sample' or 'raw'"; \
            exit 1; \
        fi; \
        if [ -n "$out_dir_arg" ]; then \
            uv run python scripts/run_bridge_probe.py --raw-data "$raw_data" --out-dir "$out_dir_arg" {{ extra }}; \
        else \
            uv run python scripts/run_bridge_probe.py --raw-data "$raw_data" {{ extra }}; \
        fi; \
    elif [ "{{ stage }}" = "study" ]; then \
        if [ "{{ dataset }}" = "sample" ]; then \
            raw_data="$sample_dataset_path"; \
            uv run python scripts/generate_sample_dataset.py; \
        elif [ "{{ dataset }}" = "raw" ]; then \
            raw_data="$raw_dataset_path"; \
            if [ ! -f "$raw_data" ]; then \
                uv run python scripts/convert_raw_dataset.py; \
            fi; \
        else \
            echo "dataset must be 'sample' or 'raw'"; \
            exit 1; \
        fi; \
        if [ -n "$out_dir_arg" ]; then \
            uv run python scripts/run_study.py --raw-data "$raw_data" --out-dir "$out_dir_arg" {{ extra }}; \
        else \
            uv run python scripts/run_study.py --raw-data "$raw_data" {{ extra }}; \
        fi; \
    else \
        echo "stage must be 'study', 'benchmark', 'cascade', or 'bridge'"; \
        exit 1; \
    fi

_fetch source="sec-bulk" extra="": _check-data-env
    uv run python scripts/fetch_public_data.py --mode "{{ source }}" {{ extra }}

data mode="full" strategy="fresh": _check-data-env
    @if [ "{{ mode }}" != "smoke" ] && [ "{{ mode }}" != "full" ]; then \
        echo "mode must be 'smoke' or 'full'"; \
        exit 1; \
    fi
    @case "{{ strategy }}" in \
        fresh|resume|force) ;; \
        *) echo "strategy must be 'fresh', 'resume', or 'force'"; exit 1 ;; \
    esac
    just setup
    @if [ "{{ strategy }}" = "force" ]; then \
        uv run python scripts/convert_raw_dataset.py --overwrite; \
    else \
        uv run python scripts/convert_raw_dataset.py; \
    fi
    @lake_args=""; \
    case "{{ strategy }}" in \
        fresh) lake_args="--fresh-build" ;; \
        resume) lake_args="--resume" ;; \
        force) lake_args="--force --fresh-build" ;; \
    esac; \
    bash scripts/run_public_lake_full.sh \
        --mode "{{ mode }}" \
        --skip-setup \
        --skip-public-cascade \
        $lake_args; \
    uv run python scripts/build_linkage_bridge.py; \
    echo "Data engineering complete: raw dataset parquet plus public lake {{ mode }}."

full *args: _check-data-env
    @mode="smoke"; dataset="sample"; out_dir=""; as_of_date="2026-07-06"; source_end_year=""; fetch_workers="2"; model_jobs="4"; model_threads="2"; engine="duckdb"; storage_format="parquet"; notes_mode="summary"; fresh_build="0"; force_fetch="0"; resume="0"; duckdb_memory_limit="10GB"; duckdb_temp_directory=""; duckdb_max_temp_size="400GB"; fsds_batch_size="4"; notes_batch_size="2"; pos=1; \
    raw_dataset_path="${RAW_DATASET_PATH:-${DATA_DIR}/raw/raw_dataset_misstatement.parquet}"; \
    sample_dataset_path="${SAMPLE_DATASET_PATH:-${ARTIFACTS_DIR}/sample_dataset_misstatement.parquet}"; \
    public_lake_dir="${PUBLIC_LAKE_DIR:-${DATA_DIR}/public_lake}"; \
    public_lake_smoke_dir="${PUBLIC_LAKE_SMOKE_DIR:-${DATA_DIR}/public_lake_smoke}"; \
    lake_silver_dir="${LAKE_SILVER_DIR:-${public_lake_dir}/silver}"; \
    lake_gold_dir="${LAKE_GOLD_DIR:-${public_lake_dir}/gold}"; \
    for arg in {{ args }}; do \
        case "$arg" in \
            mode=*) mode="${arg#mode=}" ;; \
            dataset=*) dataset="${arg#dataset=}" ;; \
            out_dir=*) out_dir="${arg#out_dir=}" ;; \
            as_of_date=*) as_of_date="${arg#as_of_date=}" ;; \
            source_end_year=*) source_end_year="${arg#source_end_year=}" ;; \
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
                    5) source_end_year="$arg" ;; \
                    6) fetch_workers="$arg" ;; \
                    7) model_jobs="$arg" ;; \
                    8) model_threads="$arg" ;; \
                    9) engine="$arg" ;; \
                    10) storage_format="$arg" ;; \
                    11) notes_mode="$arg" ;; \
                    12) fresh_build="$arg" ;; \
                    13) force_fetch="$arg" ;; \
                    14) duckdb_memory_limit="$arg" ;; \
                    15) duckdb_temp_directory="$arg" ;; \
                    16) duckdb_max_temp_size="$arg" ;; \
                    17) fsds_batch_size="$arg" ;; \
                    18) notes_batch_size="$arg" ;; \
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
    if [ -n "$source_end_year" ]; then \
        case "$source_end_year" in *[!0-9]*|"") echo "source_end_year must be a four-digit year"; exit 1 ;; esac; \
        if [ "${#source_end_year}" -ne 4 ]; then echo "source_end_year must be a four-digit year"; exit 1; fi; \
    fi; \
    run_out="$out_dir"; \
    if [ -z "$run_out" ]; then \
        run_out="${ARTIFACTS_DIR}/full_${mode}_${dataset}"; \
    else \
        case "$run_out" in \
            /*) \
                case "$run_out" in \
                    "${ARTIFACTS_DIR}"|"${ARTIFACTS_DIR}"/*|"{{ repo_root }}"|"{{ repo_root }}"/*|/tmp/*) ;; \
                    *) \
                        echo "out_dir must be relative or under ARTIFACTS_DIR; got: $run_out"; \
                        echo "If this came from an unset shell variable, use a repo-relative path like artifacts/full_with_peer."; \
                        exit 1; \
                        ;; \
                esac; \
                ;; \
        esac; \
    fi; \
    just setup; \
    just _test; \
    just _ruff; \
    uv run python scripts/convert_raw_dataset.py; \
    if [ "$dataset" = "raw" ] && [ ! -f "$raw_dataset_path" ]; then \
        echo "$raw_dataset_path is required for dataset=raw"; \
        echo "Expected ${DATA_DIR}/raw_dataset_misstatement.csv, ${DATA_DIR}/raw_dataset_misstatement.zip, ${DATA_DIR}/raw/raw_dataset_misstatement.csv, or ${DATA_DIR}/raw/raw_dataset_misstatement.zip as a materialization source."; \
        exit 1; \
    fi; \
    if [ "$dataset" = "sample" ]; then \
        uv run python scripts/generate_sample_dataset.py; \
        raw_data="$sample_dataset_path"; \
    else \
        raw_data="$raw_dataset_path"; \
    fi; \
    if [ "$mode" = "smoke" ]; then \
        silver_dir="${public_lake_smoke_dir}/silver"; \
        gold_dir="${public_lake_smoke_dir}/gold"; \
    else \
        silver_dir="$lake_silver_dir"; \
        gold_dir="$lake_gold_dir"; \
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
        --skip-public-cascade ${source_end_year:+--source-end-year "$source_end_year"} ${duckdb_temp_directory:+--duckdb-temp-directory "$duckdb_temp_directory"} $lake_args; \
    uv run python scripts/build_linkage_bridge.py; \
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

snapshot study_dir="artifacts/full_with_peer" allow_partial="0": _check-data-env
    @study_dir_arg="{{ study_dir }}"; \
    case "$study_dir_arg" in study_dir=*) study_dir_arg="${study_dir_arg#study_dir=}" ;; esac; \
    if [ -n "$study_dir_arg" ]; then \
        case "$study_dir_arg" in \
            /*) \
                case "$study_dir_arg" in \
                    "${ARTIFACTS_DIR}"|"${ARTIFACTS_DIR}"/*|"{{ repo_root }}"|"{{ repo_root }}"/*|/tmp/*) ;; \
                    *) \
                        echo "study_dir must be relative or under ARTIFACTS_DIR; got: $study_dir_arg"; \
                        echo "If this came from an unset shell variable, use a repo-relative path like artifacts/full_with_peer."; \
                        exit 1; \
                        ;; \
                esac; \
                ;; \
        esac; \
    fi; \
    partial_flag=""; \
    allow_partial_arg="{{ allow_partial }}"; \
    case "$allow_partial_arg" in allow_partial=*) allow_partial_arg="${allow_partial_arg#allow_partial=}" ;; esac; \
    case "$allow_partial_arg" in \
        0) ;; \
        1) partial_flag="--allow-partial" ;; \
        *) echo "allow_partial must be 0 or 1"; exit 1 ;; \
    esac; \
    uv run python scripts/refresh_results_snapshot.py --study-dir "$study_dir_arg" $partial_flag
    just check

manuscript study_dir="artifacts/full_with_peer" out_dir="artifacts/manuscript_package": _check-data-env
    @study_dir_arg="{{ study_dir }}"; \
    out_dir_arg="{{ out_dir }}"; \
    case "$study_dir_arg" in study_dir=*) study_dir_arg="${study_dir_arg#study_dir=}" ;; esac; \
    case "$out_dir_arg" in out_dir=*) out_dir_arg="${out_dir_arg#out_dir=}" ;; esac; \
    for path_arg in "$study_dir_arg" "$out_dir_arg"; do \
        if [ -n "$path_arg" ]; then \
            case "$path_arg" in \
                /*) \
                    case "$path_arg" in \
                        "${ARTIFACTS_DIR}"|"${ARTIFACTS_DIR}"/*|"{{ repo_root }}"|"{{ repo_root }}"/*|/tmp/*) ;; \
                        *) \
                            echo "manuscript paths must be relative or under ARTIFACTS_DIR; got: $path_arg"; \
                            echo "If this came from an unset shell variable, use repo-relative paths like artifacts/full_with_peer and artifacts/manuscript_package."; \
                            exit 1; \
                            ;; \
                    esac; \
                    ;; \
            esac; \
        fi; \
    done; \
    uv run python scripts/build_manuscript_package.py --study-dir "$study_dir_arg" --out-dir "$out_dir_arg"

_docs-build: _check-env
    uv run --group docs mkdocs build --strict --clean
