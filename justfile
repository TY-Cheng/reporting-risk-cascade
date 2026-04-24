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

setup: _check-env
    uv sync
    just _ruff

status: _check-env
    @echo "UV_PROJECT_ENVIRONMENT=${UV_PROJECT_ENVIRONMENT}"
    @echo "DIR_MANUSCRIPT=${DIR_MANUSCRIPT}"
    @echo "PROJECT_ROOT=${PROJECT_ROOT}"
    @echo "DATA_DIR=${DATA_DIR}"
    @echo "DOCS_DIR=${DOCS_DIR}"
    @echo "PAPER_DIR=${PAPER_DIR}"
    @echo "DIR_MANUSCRIPT=${DIR_MANUSCRIPT}"
    @if [ -x "${UV_PROJECT_ENVIRONMENT}/bin/python" ]; then \
        "${UV_PROJECT_ENVIRONMENT}/bin/python" -c "import sys; from src import PROJECT_ROOT, DATA_DIR, DOCS_DIR, PAPER_DIR, DIR_MANUSCRIPT, ARTIFACTS_DIR, SAMPLE_DATASET_PATH; print('python_prefix', sys.prefix); print('python_project_root', PROJECT_ROOT); print('python_data_dir', DATA_DIR); print('python_docs_dir', DOCS_DIR); print('python_paper_dir', PAPER_DIR); print('python_dir_manuscript', DIR_MANUSCRIPT); print('python_artifacts_dir', ARTIFACTS_DIR); print('python_sample_dataset_path', SAMPLE_DATASET_PATH)"; \
    else \
        echo "python_prefix missing; run 'just setup'"; \
    fi

run dataset="sample" out_dir="": _check-env
    @if [ "{{ dataset }}" != "sample" ] && [ "{{ dataset }}" != "raw" ]; then \
        echo "dataset must be 'sample' or 'raw'"; \
        exit 1; \
    fi
    @if [ -n "{{ out_dir }}" ]; then \
        uv run python scripts/run_data_prep.py --dataset "{{ dataset }}" --out-dir "{{ out_dir }}"; \
    else \
        uv run python scripts/run_data_prep.py --dataset "{{ dataset }}"; \
    fi
    just _ruff

analysis stage="study" dataset="raw" out_dir="" extra="": _check-env
    @if [ "{{ stage }}" = "benchmark" ]; then \
        if [ "{{ dataset }}" = "sample" ]; then \
            raw_csv="artifacts/sample_dataset_misstatement.csv"; \
            uv run python scripts/generate_sample_dataset.py; \
        elif [ "{{ dataset }}" = "raw" ]; then \
            raw_csv="data/raw_dataset_misstatement.csv"; \
        else \
            echo "dataset must be 'sample' or 'raw'"; \
            exit 1; \
        fi; \
        if [ -n "{{ out_dir }}" ]; then \
            uv run python scripts/run_benchmark.py --raw-csv "$raw_csv" --out-dir "{{ out_dir }}" {{ extra }}; \
        else \
            uv run python scripts/run_benchmark.py --raw-csv "$raw_csv" {{ extra }}; \
        fi; \
    elif [ "{{ stage }}" = "cascade" ]; then \
        if [ -n "{{ out_dir }}" ]; then \
            uv run python scripts/run_public_cascade.py --out-dir "{{ out_dir }}" {{ extra }}; \
        else \
            uv run python scripts/run_public_cascade.py {{ extra }}; \
        fi; \
    elif [ "{{ stage }}" = "bridge" ]; then \
        if [ "{{ dataset }}" = "sample" ]; then \
            raw_csv="artifacts/sample_dataset_misstatement.csv"; \
            uv run python scripts/generate_sample_dataset.py; \
        elif [ "{{ dataset }}" = "raw" ]; then \
            raw_csv="data/raw_dataset_misstatement.csv"; \
        else \
            echo "dataset must be 'sample' or 'raw'"; \
            exit 1; \
        fi; \
        if [ -n "{{ out_dir }}" ]; then \
            uv run python scripts/run_bridge_probe.py --raw-csv "$raw_csv" --out-dir "{{ out_dir }}" {{ extra }}; \
        else \
            uv run python scripts/run_bridge_probe.py --raw-csv "$raw_csv" {{ extra }}; \
        fi; \
    elif [ "{{ stage }}" = "study" ]; then \
        if [ "{{ dataset }}" = "sample" ]; then \
            raw_csv="artifacts/sample_dataset_misstatement.csv"; \
            uv run python scripts/generate_sample_dataset.py; \
        elif [ "{{ dataset }}" = "raw" ]; then \
            raw_csv="data/raw_dataset_misstatement.csv"; \
        else \
            echo "dataset must be 'sample' or 'raw'"; \
            exit 1; \
        fi; \
        if [ -n "{{ out_dir }}" ]; then \
            uv run python scripts/run_study.py --raw-csv "$raw_csv" --out-dir "{{ out_dir }}" {{ extra }}; \
        else \
            uv run python scripts/run_study.py --raw-csv "$raw_csv" {{ extra }}; \
        fi; \
    else \
        echo "stage must be 'study', 'benchmark', 'cascade', or 'bridge'"; \
        exit 1; \
    fi
    just _ruff

fetch source="sec-bulk" extra="": _check-env
    uv run python scripts/fetch_public_data.py --mode "{{ source }}" {{ extra }}
    just _ruff

check dataset="sample": _check-env
    @if [ "{{ dataset }}" != "sample" ] && [ "{{ dataset }}" != "raw" ]; then \
        echo "dataset must be 'sample' or 'raw'"; \
        exit 1; \
    fi
    @if [ "{{ dataset }}" = "sample" ]; then \
        uv run python scripts/run_data_prep.py --dataset sample --out-dir artifacts/sample_run; \
    else \
        uv run python scripts/run_data_prep.py --dataset raw --out-dir artifacts/raw_run; \
    fi
    just _ruff

docs: _check-env
    @for port in 8001 8002 8003 8004 8005 8006 8007 8008 8009 8010; do \
        if ! lsof -nP -iTCP:${port} -sTCP:LISTEN >/dev/null 2>&1; then \
            echo "Serving docs on http://127.0.0.1:${port}"; \
            uv run --group docs mkdocs serve --clean -a "127.0.0.1:${port}"; \
            exit 0; \
        fi; \
    done; \
    echo "No free docs port in 8001-8010"; \
    exit 1
    just _ruff

_docs-build: _check-env
    uv run --group docs mkdocs build --clean
    just _ruff
