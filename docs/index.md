# Reporting Risk Cascade Docs

!!! abstract "What this site is for"
    This docs site is the operational front door for the current reporting-risk cascade paper.
    Use it to orient the project quickly, inspect the executable paper plan, and
    keep deferred research separate from the active benchmark plus public-cascade study.

[Open the current paper plan](paper_plan.md){ .md-button .md-button--primary }
[See deferred future work](future_work.md){ .md-button }

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

    [:octicons-arrow-right-24: Jump to run surface](#run-surface)

-   :material-bridge: __Readiness and blockers__

    ---

    The public paper is gated by gold-panel availability, zero-positive tasks,
    and the eventual `gvkey-CIK-year` bridge. The docs should make those gates obvious.

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

## Run Surface

=== "Fast path"

    ```bash
    just setup
    just status
    just analysis benchmark raw
    just analysis bridge raw
    just analysis study raw
    just docs
    ```

=== "Public-lake path"

    ```bash
    just fetch sec-bulk
    just fetch form-ap
    just fetch build-lake
    bash scripts/run_public_lake_full.sh --mode smoke --submissions-max-ciks 200
    ```

=== "Docs path"

    ```bash
    just docs
    ```

    `just docs` now serves MkDocs on the first free local port in `8001-8010`,
    which avoids collisions with other repo-local dashboards and docs servers.

## Readiness Snapshot

| Layer | Current role | State |
| --- | --- | --- |
| Benchmark | `gvkey x data_year` benchmark | Evidence available, but `res_an*` supports timing sensitivity only, not paper-grade maturation |
| Public cascade | Main public-data measurement layer | Evidence under construction; metadata baseline is not enough until `xbrl_ratio_*` features land |
| Bridge | Overlap validation between old and new layers | Integration evidence pending; current raw shape should emit `raw_identifier_blocker` |

!!! note "Reading order"
    Start with the home overview below if you need the repo story in five minutes.
    Open [paper_plan.md](paper_plan.md) when you need the execution contract.
    Open [future_work.md](future_work.md) only after the current paper gates are met.

## Repo Overview

--8<-- "README.md:docs-home"
