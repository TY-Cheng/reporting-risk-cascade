<section class="rrc-hero" markdown>
<div class="rrc-kicker">Executable research docs</div>

# Reporting Risk Cascade

This site is the operational front door for the current reporting-risk cascade
paper: public-lake construction, benchmark diagnostics, cascade readiness,
bridge blockers, and the exact commands needed to reproduce the active results.

<div class="rrc-hero__actions" markdown>
[Open the paper plan](paper_plan.md){ .md-button .md-button--primary }
[View results](results_snapshot.md){ .md-button }
[Run commands](#reproducible-commands){ .md-button }
</div>

<div class="rrc-badge-row">
  <span class="rrc-badge">Parquet-first public lake</span>
  <span class="rrc-badge">95% core coverage gate</span>
  <span class="rrc-badge">Strict docs build</span>
  <span class="rrc-badge">Bridge gate explicit</span>
</div>
</section>

<div class="grid cards" markdown>

-   :material-file-document-edit-outline: __Current paper__

    ---

    The active study is a measurement and prediction paper about label maturation,
    concept drift, strategic missingness, and the public reporting-risk cascade.

    [:octicons-arrow-right-24: Paper plan](paper_plan.md)

-   :material-play-circle-outline: __Actual workflow__

    ---

    The repo front door is `just`. Benchmark, public-cascade, study, and docs
    commands are all routed through the same small command surface.

    [:octicons-arrow-right-24: Jump to commands](#reproducible-commands)

-   :material-chart-box-outline: __Current results__

    ---

    The site includes a static snapshot of the current `artifacts/full` run:
    public-lake scale, cascade readiness, benchmark diagnostics, and bridge status.

    [:octicons-arrow-right-24: Results snapshot](results_snapshot.md)

-   :material-bridge: __Readiness and blockers__

    ---

    The public paper is gated by gold-panel availability, zero-positive tasks,
    and the eventual `gvkey-CIK-year` bridge. The docs should make those gates obvious.
    Large public-lake panels are Parquet-first so repeated full runs do not spend
    most of their time decompressing and rewriting gzip CSV; the DuckDB path now
    builds the Gold panels directly in SQL before writing Parquet.

    [:octicons-arrow-right-24: Jump to readiness](#readiness-snapshot)

-   :material-road-variant: __Deferred roadmap__

    ---

    Multimodal text, graph structure, attention layers, and richer detector labels
    are explicitly deferred until the current measurement spine is reproducible.

    [:octicons-arrow-right-24: Future work](future_work.md)

-   :material-clipboard-search-outline: __Audit prompts__

    ---

    Use the development prompt to audit code against `paper_plan.md`; use the
    manuscript prompt to audit the paper draft against the same research contract.

    [:octicons-arrow-right-24: Development audit](development_audit_prompt.md)
    [:octicons-arrow-right-24: Manuscript audit](manuscript_audit_prompt.md)

</div>

## Reproducible Commands

=== "Fast path"

    ```bash
    just setup
    just status
    just task benchmark raw
    just task bridge raw
    just task study raw
    just docs
    ```

=== "Complete path"

    ```bash
    just full smoke sample artifacts/full_smoke_sample
    just full full raw artifacts/full
    just full mode="smoke" dataset="sample" out_dir="artifacts/full_smoke_sample" fetch_workers="2" model_jobs="2" model_threads="4" engine="duckdb" storage_format="parquet" notes_mode="summary" fresh_build="1" duckdb_memory_limit="10GB" duckdb_max_temp_size="50GB" fsds_batch_size="4" notes_batch_size="2"
    ```

=== "Public-lake path"

    ```bash
    just task sec-bulk
    just task form-ap
    just task build-lake
    bash scripts/run_public_lake_full.sh --mode smoke --submissions-max-ciks 200 --fetch-workers 2 --engine duckdb --duckdb-threads 4 --duckdb-memory-limit 10GB --duckdb-max-temp-size 50GB --fsds-batch-size 4 --notes-batch-size 2 --storage-format parquet --notes-mode summary --fresh-build
    ```

=== "Docs path"

    ```bash
    just docs
    ```

    `just docs` first runs a strict clean MkDocs build, then serves MkDocs on
    the first free local port in `8001-8010`, which avoids stale pages and local
    port collisions.

## Readiness Snapshot

| Layer | Current role | State |
| --- | --- | --- |
| Benchmark | `gvkey x data_year` benchmark | Evidence available; the code emits `naive`, `proxy_drop_observed`, and `proxy_imputed_lag_*y` rows, but external timing is still needed for paper-grade maturation |
| Public cascade | Main public-data measurement layer | Full-run snapshot available; current readiness is `xbrl_ratio_baseline` with nonzero XBRL ratio features; public-label opacity DML is implemented and refreshes on the next study run |
| Bridge | Overlap validation between old and new layers | Integration evidence pending until `data/external/gvkey_cik_year.csv` is prepared from an authoritative WRDS/Compustat-style CIK-GVKEY source |

!!! info "Bridge crosswalk"
    The repo can normalize and validate an external `gvkey-CIK-year` crosswalk,
    but it cannot derive one from the current raw benchmark alone. Use
    `scripts/prepare_gvkey_cik_crosswalk.py` on a WRDS/Compustat CIK-GVKEY export,
    then rerun `just task bridge raw`.

!!! note "Reading order"
    Start with the home overview below if you need the repo story in five minutes.
    Open [paper_plan.md](paper_plan.md) when you need the execution contract.
    Open [future_work.md](future_work.md) only after the current paper gates are met.

## Repository Overview

--8<-- "README.md:docs-home"
