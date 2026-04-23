set dotenv-load := true
set export := true
set shell := ["bash", "-euo", "pipefail", "-c"]

default:
    @just --list

setup:
    @test -n "${UV_PROJECT_ENVIRONMENT}" || { echo "UV_PROJECT_ENVIRONMENT is missing in .env"; exit 1; }
    @test -n "${DIR_MANUSCRIPT}" || { echo "DIR_MANUSCRIPT is missing in .env"; exit 1; }
    @echo "UV_PROJECT_ENVIRONMENT=${UV_PROJECT_ENVIRONMENT}"
    @echo "DIR_MANUSCRIPT=${DIR_MANUSCRIPT}"
    @mkdir -p "$(dirname "${UV_PROJECT_ENVIRONMENT}")"
    uv lock
    uv sync

status:
    @test -n "${UV_PROJECT_ENVIRONMENT}" || { echo "UV_PROJECT_ENVIRONMENT is missing in .env"; exit 1; }
    @test -n "${DIR_MANUSCRIPT}" || { echo "DIR_MANUSCRIPT is missing in .env"; exit 1; }
    @echo "PROJECT_ROOT=${PROJECT_ROOT}"
    @echo "DATA_DIR=${DATA_DIR}"
    @echo "DOCS_DIR=${DOCS_DIR}"
    @echo "PAPER_DIR=${PAPER_DIR}"
    @echo "DIR_MANUSCRIPT=${DIR_MANUSCRIPT}"
    uv run python -c "from src import PROJECT_ROOT, DATA_DIR, DOCS_DIR, PAPER_DIR, DIR_MANUSCRIPT, ARTIFACTS_DIR, SAMPLE_DATASET_PATH; print('python_project_root', PROJECT_ROOT); print('python_data_dir', DATA_DIR); print('python_docs_dir', DOCS_DIR); print('python_paper_dir', PAPER_DIR); print('python_dir_manuscript', DIR_MANUSCRIPT); print('python_artifacts_dir', ARTIFACTS_DIR); print('python_sample_dataset_path', SAMPLE_DATASET_PATH)"

run dataset="sample" out_dir="":
    @test -n "${UV_PROJECT_ENVIRONMENT}" || { echo "UV_PROJECT_ENVIRONMENT is missing in .env"; exit 1; }
    @if [ "{{dataset}}" != "sample" ] && [ "{{dataset}}" != "raw" ]; then \
        echo "dataset must be 'sample' or 'raw'"; \
        exit 1; \
    fi
    @if [ -n "{{out_dir}}" ]; then \
        uv run python scripts/run_data_prep.py --dataset "{{dataset}}" --out-dir "{{out_dir}}"; \
    else \
        uv run python scripts/run_data_prep.py --dataset "{{dataset}}"; \
    fi

analysis stage="paper1" dataset="raw" out_dir="" extra="":
    @test -n "${UV_PROJECT_ENVIRONMENT}" || { echo "UV_PROJECT_ENVIRONMENT is missing in .env"; exit 1; }
    @if [ "{{stage}}" = "paper1" ]; then \
        if [ "{{dataset}}" = "sample" ]; then \
            raw_csv="artifacts/sample_dataset_misstatement.csv"; \
            uv run python scripts/generate_sample_dataset.py; \
        elif [ "{{dataset}}" = "raw" ]; then \
            raw_csv="data/raw_dataset_misstatement.csv"; \
        else \
            echo "dataset must be 'sample' or 'raw'"; \
            exit 1; \
        fi; \
        if [ -n "{{out_dir}}" ]; then \
            uv run python scripts/run_paper1.py --raw-csv "$raw_csv" --out-dir "{{out_dir}}" {{extra}}; \
        else \
            uv run python scripts/run_paper1.py --raw-csv "$raw_csv" {{extra}}; \
        fi; \
    elif [ "{{stage}}" = "paper2" ]; then \
        if [ -n "{{out_dir}}" ]; then \
            uv run python scripts/run_paper2.py --out-dir "{{out_dir}}" {{extra}}; \
        else \
            uv run python scripts/run_paper2.py {{extra}}; \
        fi; \
    else \
        echo "stage must be 'paper1' or 'paper2'"; \
        exit 1; \
    fi

fetch source="references" extra="":
    @test -n "${UV_PROJECT_ENVIRONMENT}" || { echo "UV_PROJECT_ENVIRONMENT is missing in .env"; exit 1; }
    @if [ "{{source}}" = "references" ]; then \
        uv run python scripts/fetch_public_data.py --mode references {{extra}}; \
    elif [ "{{source}}" = "sec-index" ]; then \
        uv run python scripts/fetch_public_data.py --mode sec-index {{extra}}; \
    elif [ "{{source}}" = "sec-download" ]; then \
        uv run python scripts/fetch_public_data.py --mode sec-download {{extra}}; \
    else \
        echo "source must be 'references', 'sec-index', or 'sec-download'"; \
        exit 1; \
    fi

check dataset="sample":
    @test -n "${UV_PROJECT_ENVIRONMENT}" || { echo "UV_PROJECT_ENVIRONMENT is missing in .env"; exit 1; }
    @if [ "{{dataset}}" != "sample" ] && [ "{{dataset}}" != "raw" ]; then \
        echo "dataset must be 'sample' or 'raw'"; \
        exit 1; \
    fi
    uv run ruff check src scripts
    @if [ "{{dataset}}" = "sample" ]; then \
        uv run python scripts/run_data_prep.py --dataset sample --out-dir artifacts/sample_run; \
    else \
        uv run python scripts/run_data_prep.py --dataset raw --out-dir artifacts/raw_run; \
    fi

format:
    uv run ruff format src scripts

docs action="build":
    @if [ "{{action}}" = "build" ]; then \
        uv run --group docs mkdocs build --clean; \
    elif [ "{{action}}" = "serve" ]; then \
        uv run --group docs mkdocs serve; \
    else \
        echo "action must be 'build' or 'serve'"; \
        exit 1; \
    fi
