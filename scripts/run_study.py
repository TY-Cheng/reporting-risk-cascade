"""
Run the combined benchmark + public cascade study workflow.

The study paper keeps the old gvkey firm-year CSV as the benchmark layer and
the filing-native public lake as the main public-cascade layer. This script
orchestrates both components and records what is still missing for the bridge
validation layer.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import yaml

REPO_ROOT = Path(__file__).resolve().parents[1]


def _bootstrap_repo_root() -> None:
    if str(REPO_ROOT) not in sys.path:
        sys.path.insert(0, str(REPO_ROOT))


def _load_yaml(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    return yaml.safe_load(path.read_text(encoding="utf-8")) or {}


def _resolve_project_path(
    value: str | Path | None,
    *,
    default: Path,
    data_dir: Path,
    artifacts_dir: Path,
) -> Path:
    if value is None or str(value) == "":
        return default
    path = Path(os.path.expandvars(str(value))).expanduser()
    if path.is_absolute():
        return path
    if path.parts and path.parts[0] == "data":
        return data_dir.joinpath(*path.parts[1:])
    if path.parts and path.parts[0] == "artifacts":
        return artifacts_dir.joinpath(*path.parts[1:])
    return REPO_ROOT / path


def _existing_or_skipped_component(
    *,
    should_run: bool,
    out_dir: Path,
    summary_name: str,
    manifest_name: str,
) -> dict[str, str]:
    if should_run:
        return {"status": "pending"}
    manifest_path = out_dir / manifest_name
    if manifest_path.exists():
        component = {
            "status": "existing",
            "out_dir": str(out_dir),
            "manifest_json": str(manifest_path),
        }
        summary_path = out_dir / summary_name
        if summary_path.exists():
            component["summary_md"] = str(summary_path)
        return component
    return {"status": "skipped"}


def parse_args() -> argparse.Namespace:
    _bootstrap_repo_root()

    from src import ARTIFACTS_DIR, PROJECT_ROOT

    parser = argparse.ArgumentParser(
        description="Run the benchmark + public cascade study workflow"
    )
    parser.add_argument(
        "--config",
        type=Path,
        default=PROJECT_ROOT / "config" / "study.yaml",
        help="Path to the study YAML config",
    )
    parser.add_argument(
        "--benchmark-config",
        type=Path,
        default=PROJECT_ROOT / "config" / "benchmark.yaml",
        help="Path to the benchmark YAML config",
    )
    parser.add_argument(
        "--public-cascade-config",
        type=Path,
        default=PROJECT_ROOT / "config" / "public_cascade.yaml",
        help="Path to the public cascade YAML config",
    )
    parser.add_argument(
        "--raw-data",
        type=Path,
        default=None,
        help="Path to the old gvkey firm-year table",
    )
    parser.add_argument(
        "--raw-csv",
        type=Path,
        default=None,
        help="Deprecated alias for --raw-data",
    )
    parser.add_argument(
        "--timing-csv",
        type=Path,
        default=None,
        help="Optional external timing CSV for benchmark label maturation",
    )
    parser.add_argument(
        "--issuer-origin-panel",
        type=Path,
        default=None,
        help="Issuer-level public-lake gold panel for public cascade",
    )
    parser.add_argument(
        "--issuer-dim",
        type=Path,
        default=None,
        help="Public-lake silver issuer dimension for the bridge probe",
    )
    parser.add_argument(
        "--crosswalk",
        type=Path,
        default=None,
        help="Optional gvkey-CIK-year crosswalk for overlap validation",
    )
    parser.add_argument(
        "--out-dir",
        type=Path,
        default=ARTIFACTS_DIR / "study",
        help="Directory for combined study outputs",
    )
    parser.add_argument("--skip-benchmark", action="store_true", help="Do not rerun benchmark")
    parser.add_argument(
        "--skip-public-cascade",
        action="store_true",
        help="Do not rerun public cascade",
    )
    parser.add_argument("--skip-bridge-probe", action="store_true", help="Do not run bridge probe")
    parser.add_argument(
        "--skip-construct-overlap",
        action="store_true",
        help="Do not run candidate bridge construct-overlap validation",
    )
    parser.add_argument(
        "--parallel-jobs",
        type=int,
        default=None,
        help="Outer model workers for benchmark and public cascade",
    )
    parser.add_argument(
        "--model-threads",
        type=int,
        default=None,
        help="Threads per model fit for benchmark and public cascade",
    )
    parser.add_argument(
        "--seed-policy",
        choices=["task-isolated", "legacy"],
        default=None,
        help="Random seed policy for model tasks",
    )
    parser.add_argument(
        "--peer-comparison-mode",
        choices=["none", "light", "full"],
        default=None,
        help="Run peer-compatible model-family comparison suites",
    )
    parser.add_argument(
        "--peer-target",
        choices=["legacy", "public", "both"],
        default=None,
        help=(
            "Peer suite target. Use public with --peer-comparison-mode full to refresh "
            "public-label peer transfer without rerunning legacy peer outputs."
        ),
    )
    return parser.parse_args()


def _write_summary(
    *,
    out_dir: Path,
    manifest: dict[str, Any],
    crosswalk_path: Path,
    crosswalk_exists: bool,
) -> None:
    lines = [
        "# Study Workflow Summary",
        "",
        "## Claim",
        "- Combine the old restatement benchmark with the filing-native public cascade.",
        "- The estimand is a pre-disclosure public reporting-risk state, not latent true fraud.",
        "",
        "## Completed Components",
    ]
    for key in ["benchmark", "public_cascade", "peer_comparison", "public_peer_comparison"]:
        if key not in manifest["components"]:
            continue
        status = manifest["components"][key].get(
            "status", manifest["components"][key].get("run_status", "unknown")
        )
        out = manifest["components"][key].get("out_dir", "")
        lines.append(f"- `{key}`: {status}; output: `{out}`")

    lines.extend(
        [
            "",
            "## Bridge Layer",
            f"- Crosswalk path: `{crosswalk_path}`",
            f"- Crosswalk available: `{crosswalk_exists}`",
        ]
    )
    if not crosswalk_exists:
        lines.append(
            "- Next required input: `gvkey-CIK-year` crosswalk to validate old restatement "
            "labels against public cascade labels."
        )
    bridge_probe = manifest["components"].get("bridge_probe", {})
    if bridge_probe:
        lines.append(f"- Bridge probe status: `{bridge_probe.get('status')}`")
        if bridge_probe.get("summary_json"):
            lines.append(f"- Bridge probe summary: `{bridge_probe.get('summary_json')}`")
    construct_overlap = manifest["components"].get("construct_overlap", {})
    if construct_overlap:
        lines.append(
            f"- Construct-overlap status: `{construct_overlap.get('run_status')}`; "
            f"validation tier: `{construct_overlap.get('validation_tier')}`"
        )

    lines.extend(
        [
            "",
            "## Main Outputs To Read First",
            "- `benchmark/benchmark_summary.md`",
            "- `public_cascade/public_cascade_summary.md`",
            "- `peer_comparison/peer_comparison_summary.md` when peer mode is enabled",
            "- `public_peer_comparison/public_model_family_summary.md` when peer full mode is enabled",
            "- `construct_overlap/construct_overlap_summary.md` when bridge validation runs",
            "- `study_run_manifest.json`",
        ]
    )
    (out_dir / "study_summary.md").write_text("\n".join(lines) + "\n", encoding="utf-8")


def main() -> None:
    _bootstrap_repo_root()

    from src import ARTIFACTS_DIR, DATA_DIR, LAKE_GOLD_DIR, LAKE_SILVER_DIR, RAW_DATASET_PATH
    from src.benchmark import run_benchmark
    from src.bridge import run_bridge_probe
    from src.construct_overlap import run_construct_overlap
    from src.linkage import DEFAULT_LINKAGE_OUT_DIR
    from src.peer_comparison import run_peer_comparison
    from src.public_cascade import run_public_cascade
    from src.public_peer_comparison import run_public_peer_comparison

    args = parse_args()
    cfg = _load_yaml(args.config)
    inputs = cfg.get("inputs", {})
    outputs = cfg.get("outputs", {})
    peer_cfg = dict(cfg.get("peer_comparison", {}))
    if args.parallel_jobs is not None:
        peer_cfg["parallel_jobs"] = args.parallel_jobs
    if args.model_threads is not None:
        peer_cfg["model_threads"] = args.model_threads
    peer_mode = args.peer_comparison_mode or str(peer_cfg.get("mode", "none"))
    peer_target = args.peer_target or str(peer_cfg.get("target", "both"))
    if peer_target not in {"legacy", "public", "both"}:
        raise ValueError("peer target must be one of: legacy, public, both")
    run_legacy_peer = peer_mode != "none" and peer_target in {"legacy", "both"}
    run_public_peer = peer_mode == "full" and peer_target in {"public", "both"}

    raw_data_arg = args.raw_data or args.raw_csv
    raw_csv = _resolve_project_path(
        raw_data_arg or inputs.get("raw_data") or inputs.get("raw_csv"),
        default=RAW_DATASET_PATH,
        data_dir=DATA_DIR,
        artifacts_dir=ARTIFACTS_DIR,
    )
    issuer_origin_panel = _resolve_project_path(
        args.issuer_origin_panel or inputs.get("issuer_origin_panel"),
        default=LAKE_GOLD_DIR / "issuer_origin_panel.parquet",
        data_dir=DATA_DIR,
        artifacts_dir=ARTIFACTS_DIR,
    )
    issuer_dim = _resolve_project_path(
        args.issuer_dim or inputs.get("issuer_dim"),
        default=LAKE_SILVER_DIR / "issuer_dim.parquet",
        data_dir=DATA_DIR,
        artifacts_dir=ARTIFACTS_DIR,
    )
    crosswalk = _resolve_project_path(
        args.crosswalk or inputs.get("gvkey_cik_crosswalk"),
        default=DEFAULT_LINKAGE_OUT_DIR / "gvkey_cik_year.csv",
        data_dir=DATA_DIR,
        artifacts_dir=ARTIFACTS_DIR,
    )
    benchmark_out = args.out_dir / str(outputs.get("benchmark_subdir", "benchmark"))
    public_cascade_out = args.out_dir / str(outputs.get("public_cascade_subdir", "public_cascade"))
    bridge_probe_out = args.out_dir / str(outputs.get("bridge_probe_subdir", "bridge_probe"))
    peer_comparison_out = args.out_dir / str(
        outputs.get("peer_comparison_subdir", "peer_comparison")
    )
    public_peer_comparison_out = args.out_dir / str(
        outputs.get("public_peer_comparison_subdir", "public_peer_comparison")
    )
    construct_overlap_out = args.out_dir / str(
        outputs.get("construct_overlap_subdir", "construct_overlap")
    )
    opacity_refresh_out = args.out_dir / str(
        outputs.get("opacity_validation_refresh_subdir", "opacity_validation_refresh")
    )
    args.out_dir.mkdir(parents=True, exist_ok=True)

    manifest: dict[str, Any] = {
        "generated_at_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "config": str(args.config),
        "components": {
            "benchmark": {"status": "skipped" if args.skip_benchmark else "pending"},
            "public_cascade": {"status": "skipped" if args.skip_public_cascade else "pending"},
            "bridge_probe": {"status": "skipped" if args.skip_bridge_probe else "pending"},
            "peer_comparison": _existing_or_skipped_component(
                should_run=run_legacy_peer,
                out_dir=peer_comparison_out,
                summary_name="peer_comparison_summary.md",
                manifest_name="peer_comparison_manifest.json",
            ),
            "public_peer_comparison": _existing_or_skipped_component(
                should_run=run_public_peer,
                out_dir=public_peer_comparison_out,
                summary_name="public_model_family_summary.md",
                manifest_name="public_model_family_manifest.json",
            ),
            "construct_overlap": {
                "run_status": "skipped" if args.skip_construct_overlap else "pending",
                "validation_tier": "none",
            },
        },
        "inputs": {
            "raw_data": str(raw_csv),
            "issuer_dim": str(issuer_dim),
            "issuer_origin_panel": str(issuer_origin_panel),
            "crosswalk": str(crosswalk),
        },
        "runtime": {
            "parallel_jobs": args.parallel_jobs,
            "model_threads": args.model_threads,
            "seed_policy": args.seed_policy,
            "peer_comparison_mode": peer_mode,
            "peer_target": peer_target,
            "peer_parallel_jobs": int(peer_cfg.get("parallel_jobs", 1)),
            "peer_model_threads": int(peer_cfg.get("model_threads", 1)),
        },
    }

    if not args.skip_benchmark:
        if not raw_csv.exists():
            raise FileNotFoundError(f"benchmark raw table not found: {raw_csv}")
        run_benchmark(
            config_path=args.benchmark_config,
            raw_csv=raw_csv,
            out_dir=benchmark_out,
            timing_csv=args.timing_csv,
            parallel_jobs=args.parallel_jobs,
            model_threads=args.model_threads,
            seed_policy=args.seed_policy.replace("-", "_") if args.seed_policy else None,
        )
        manifest["components"]["benchmark"] = {
            "status": "complete",
            "out_dir": str(benchmark_out),
        }

    if run_legacy_peer:
        if not raw_csv.exists():
            raise FileNotFoundError(f"peer comparison raw table not found: {raw_csv}")
        peer_summary = run_peer_comparison(
            config_path=args.benchmark_config,
            raw_data_path=raw_csv,
            out_dir=peer_comparison_out,
            mode=peer_mode,
            peer_config=peer_cfg,
            timing_csv=args.timing_csv,
        )
        manifest["components"]["peer_comparison"] = {
            "status": "complete",
            "out_dir": str(peer_comparison_out),
            "summary_md": str(peer_summary["summary_md"]),
            "manifest_json": str(peer_summary["manifest_json"]),
        }

    if not args.skip_public_cascade:
        if not issuer_origin_panel.exists():
            raise FileNotFoundError(
                "public cascade issuer_origin_panel not found. Build the public lake first or pass "
                f"--issuer-origin-panel explicitly. Missing path: {issuer_origin_panel}"
            )
        run_public_cascade(
            config_path=args.public_cascade_config,
            issuer_origin_panel_path=issuer_origin_panel,
            out_dir=public_cascade_out,
            parallel_jobs=args.parallel_jobs,
            model_threads=args.model_threads,
            seed_policy=args.seed_policy.replace("-", "_") if args.seed_policy else None,
        )
        manifest["components"]["public_cascade"] = {
            "status": "complete",
            "out_dir": str(public_cascade_out),
        }

    if run_public_peer:
        if not issuer_origin_panel.exists():
            raise FileNotFoundError(
                "public peer comparison issuer_origin_panel not found. Build the public lake first "
                f"or pass --issuer-origin-panel explicitly. Missing path: {issuer_origin_panel}"
            )
        public_peer_summary = run_public_peer_comparison(
            config_path=args.public_cascade_config,
            issuer_origin_panel_path=issuer_origin_panel,
            out_dir=public_peer_comparison_out,
            mode=peer_mode,
            peer_config=peer_cfg,
        )
        manifest["components"]["public_peer_comparison"] = {
            "status": "complete",
            "out_dir": str(public_peer_comparison_out),
            "summary_md": str(public_peer_summary["summary_md"]),
            "manifest_json": str(public_peer_summary["manifest_json"]),
        }

    if not args.skip_bridge_probe:
        if not raw_csv.exists():
            raise FileNotFoundError(f"bridge raw table not found: {raw_csv}")
        bridge_summary = run_bridge_probe(
            raw_data_path=raw_csv,
            out_dir=bridge_probe_out,
            issuer_dim_path=issuer_dim,
            issuer_origin_panel_path=issuer_origin_panel,
            crosswalk_path=crosswalk,
        )
        manifest["components"]["bridge_probe"] = {
            "status": bridge_summary.get("status", "unknown"),
            "out_dir": str(bridge_probe_out),
            "summary_json": str(bridge_probe_out / "bridge_probe_summary.json"),
        }

    if not args.skip_construct_overlap:
        overlap_summary = run_construct_overlap(
            study_dir=args.out_dir,
            out_dir=construct_overlap_out,
            opacity_out_dir=opacity_refresh_out,
            crosswalk_path=crosswalk,
            issuer_origin_panel_path=issuer_origin_panel,
        )
        manifest["components"]["construct_overlap"] = {
            "run_status": overlap_summary.get("run_status", "unknown"),
            "validation_tier": overlap_summary.get("validation_tier", "none"),
            "out_dir": str(construct_overlap_out),
            "summary_md": str(construct_overlap_out / "construct_overlap_summary.md"),
            "manifest_json": str(construct_overlap_out / "construct_overlap_manifest.json"),
        }

    crosswalk_exists = crosswalk.exists()
    manifest["bridge"] = {
        "status": "ready" if crosswalk_exists else "waiting_for_crosswalk",
        "crosswalk_exists": crosswalk_exists,
        "probe_out_dir": str(bridge_probe_out),
    }
    (args.out_dir / "study_run_manifest.json").write_text(
        json.dumps(manifest, indent=2), encoding="utf-8"
    )
    _write_summary(
        out_dir=args.out_dir,
        manifest=manifest,
        crosswalk_path=crosswalk,
        crosswalk_exists=crosswalk_exists,
    )
    print(json.dumps(manifest, indent=2))


if __name__ == "__main__":
    main()
