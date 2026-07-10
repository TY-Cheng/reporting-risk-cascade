---
hide:
  - navigation
---

# FAQ

## Core Design

### What is the research question?

Can filing-origin public SEC/PCAOB information predict whether an issuer later
enters observable public review-and-correction channels, and how does that
public reporting-risk construct relate to, but differ from, the
detected-misstatement benchmark?

The filing origin fixes the information set. Predictors must be public at or
before `origin_date`; the outcomes are later observable review or correction
events. The design therefore studies a public review-and-correction cascade,
not latent fraud truth.

### What is the empirical object?

The public cascade contains three 365-day labels:

| Label | Interpretation |
| --- | --- |
| `comment_thread` | Public SEC comment-letter scrutiny. |
| `amendment` | Amendment, correction, or filing friction. |
| `8k_402` | Item 4.02 non-reliance or material-correction signal. |

These are public observability states. They are related to reporting risk but
not interchangeable with fraud, restatement, or enforcement truth, and a
positive later-stage label does not mechanically imply an earlier-stage label.

### Which document owns design and which owns results?

The paper plan is the design contract. The results snapshot is the
artifact-backed current evidence report. This FAQ explains the design in stable
prose; it does not duplicate live estimates or choose a best-performing row.
Current values, figures, tables, provenance, and evidence boundaries belong in
the [generated results snapshot](results_snapshot.md).

## Data and Source Contracts

### What data layers are used?

| Layer | Unit | Role |
| --- | --- | --- |
| Detected-misstatement benchmark | `gvkey x data_year` | Timing, drift, missingness, and peer-model diagnostics. |
| Public SEC/PCAOB lake | Filings, facts, and public events | Source construction for filings, XBRL, Notes summaries, comment letters, amendments, Item 4.02, Form AP, and PCAOB inspections. |
| Public gold panel | `issuer_cik x fiscal_year x origin_date` | Main public issuer-year prediction surface. |
| Linkage bridge | `gvkey-CIK-year` | Construct-overlap validation only. |

The paper-facing public source contract pins `as_of_date=2026-07-06` and fiscal
years 2011-2024. Realized sample counts are generated from the canonical run and
reported in the results snapshot rather than maintained here.

### What public sources are in the lake?

The lake uses SEC submissions and filing indexes, SEC Financial Statement Data
Sets and XBRL, SEC Notes summaries, public `UPLOAD` and `CORRESP` filings,
10-K/A and 10-Q/A amendments, 8-K Item 4.02 disclosures, PCAOB Form AP, and
PCAOB inspection data. The main cascade is therefore a public-data design; the
detected-misstatement benchmark and crosswalk remain separate validation
inputs.

### How is Form AP freshness enforced?

The archive is authoritative when `FirmFilings.zip` is present. Its metadata
sidecar hash must verify, the archive must contain exactly one
`FirmFilings.csv` member, and extraction must complete before the derived CSV
is atomically replaced. A missing sidecar, invalid archive, or missing member
fails closed and never selects an older CSV. A standalone CSV is a compatibility
fallback only when the ZIP is absent.

### What is the difference between raw, external, linkage, and public_lake?

`raw/` contains the detected-misstatement benchmark input and the raw
`CIK-GVKEY Link Table.csv`. `external/` is outside the current paper-facing
bridge contract. `linkage/raw_only/` contains the derived crosswalk and bridge
QA. `public_lake/` contains the SEC/PCAOB bronze, silver, and gold layers.
`public_lake_smoke` is a bounded operational diagnostic, not the paper-facing
evidence source.

### Why is the bridge raw-only?

The rule is explicit:

1. Use the raw `CIK-GVKEY Link Table.csv` for bridge rows.
2. Do not supplement missing raw `gvkey x year` rows with external gvkey-CIK rows.
3. Report coverage, multiplicity, unmatched rows, and public overlap from the
   resulting raw-only bridge.

The bridge is WRDS-validated through the collaborator-provided SEC Analytics
Suite export, and canonical artifacts record `validation_tier = wrds_validated`.
It supports a related-but-non-identical construct interpretation, not causal or
same-estimand claims.

## Historical conflict counts

The following historical conflict counts come from the earlier raw-primary
plus external-supplement diagnostic. They are dated sensitivity evidence, not
current bridge coverage or current bridge counts.

| Historical diagnostic | Dated count |
| --- | ---: |
| Raw benchmark rows affected by Disjoint raw/external conflict `gvkey x year` cells | 372 |
| Positive Raw benchmark rows affected by those conflicts | 24 |

The default raw-only crosswalk no longer uses the external candidate rows that
produced these disagreements.

## Preprocessing and Information Sets

### What does the pipeline do?

The benchmark, public cascade, and validation bridge remain separate tracks.
The public-cascade model does not need the benchmark-to-public bridge; the
bridge is used only to ask how public labels and detected-misstatement labels
overlap after both prediction tasks have been constructed independently.

### What is the modeling grain?

The benchmark grain is `gvkey x data_year`. The public grain is
`issuer_cik x fiscal_year x origin_date`. The bridge grain is
`gvkey-CIK-year`. These distinctions prevent a cross-source mapping from
silently becoming part of public label or predictor construction.

### How is leakage controlled?

- Public predictors must be visible at or before `origin_date`.
- Rolling public histories require `event_date < origin_date`.
- Labels, censoring flags, identifiers, source-availability fields, public
  dates, vintage fields, and direct event dates are excluded from predictors.
- Benchmark `res_an0` through `res_an3` are timing proxies only.
- Numeric values retain native missingness; categorical transformations are fit
  on training years and then applied to the held-out year.

### What is the visibility/history baseline?

The visibility/history information set contains filing visibility, filing
persistence, pre-origin filing friction, and prior public-event histories. The
comparison asks whether `all` adds ranking information beyond that compact
information set. It is not a causal correction for regulator or disclosure
selection.

The notes/disclosure-breadth variables enter `all`; there is no standalone
text-family ablation. This keeps the reported feature-family vocabulary aligned
with the implemented model grid.

## Models and Selection

### What are the main models?

The public core model is XGBoost. The detected-misstatement and public peer
suites use Dechow-, Perols-, Bao-, and Bertomeu-style model-family vocabulary
where the available variable mappings support it. Those adapters are
compatibility checks, not exact replications of the original samples, labels,
or private-data settings. The opacity analysis uses cross-fitted partially
linear DML as an adjusted-association diagnostic, not causal identification.

### What is the primary public specification?

The sole headline public specification is the revision-frozen `all + expanding`
analysis. “Revision-frozen” records a design choice made during revision; it
does not imply preregistration. Table 3 and Figure 1 use this specification.
Feature-family and rolling-window grids are sensitivity evidence.

The model uses the tracked XGBoost parameters, prevalence-based training-fold
weighting, base seed 42 with task-isolated deterministic seeds, and annual
out-of-time evaluation. One-class train or test folds are skipped and reported.

### Are the benchmark and public tasks the same X with different Y?

No. The detected-misstatement benchmark uses a `gvkey x data_year` feature table
and detected-misstatement labels. The public cascade uses a public SEC/PCAOB
`issuer_cik x fiscal_year x origin_date` panel and later public
review-and-correction labels. The tasks share model-family language and metric
vocabulary, not an identical information set or estimand.

## Metrics and Interpretation

### Which metrics are reported?

The common vocabulary includes PR-AUC relative to prevalence, ROC-AUC, Brier
score, Brier Skill Score, expected calibration error, top-k precision,
top-decile precision/FDR/lift, and Bao-style top-fraction metrics.

PR-AUC is the primary headline ranking metric because the public tasks are
imbalanced and prevalence is the natural random-ranking baseline. Brier and
Brier Skill evaluate probability error relative to a prevalence forecast;
expected calibration error summarizes bin-level miscalibration. These metrics
address distinct ranking and calibration questions.

### How should comparisons be read?

Comparisons are valid within the same task, split, feature family, and label
definition. Cross-estimand comparisons do not establish that the benchmark and
public cascade measure the same latent outcome. Construct-alignment tables ask
whether the two empirical objects are related after respecting their distinct
grains and information sets.

### Where are current results reported?

All current estimates, selected evidence rows, sensitivities, sample attrition,
and provenance are generated into the
[results snapshot](results_snapshot.md). This FAQ intentionally contains no
current metric table and no best-model claim.

## Claim Boundaries

### What may the paper claim?

The design can support evidence that filing-origin public information ranks
later public review-and-correction states, and that those states have bounded
construct overlap with detected-misstatement labels. The exact strength of
those statements is controlled by the canonical manifest and generated
evidence.

### What must it not claim?

It must not claim that public labels are true fraud labels, that the model
causally identifies scrutiny or correction, that comment letters exhaust the
SEC review universe, or that cross-task PR-AUC values form a same-estimand
leaderboard. WRDS-validated linkage does not authorize unobserved true-fraud
occurrence claims.

## Reproducibility

### What is the canonical paper run?

Use `just check` for the data-free quality gate. For the paper-facing run,
rebuild the data layer once and then run the peer-enabled study once:

```bash
just data full fresh
just task study raw artifacts/full_with_peer \
  extra="--peer-comparison-mode full --peer-target both --parallel-jobs 4 --model-threads 2 --seed-policy task-isolated"
just snapshot study_dir=artifacts/full_with_peer
just verify-canonical study_dir=artifacts/full_with_peer package_dir=artifacts/manuscript_package
just reviewer-package study_dir=artifacts/full_with_peer package_dir=artifacts/manuscript_package
```

`just full mode=full dataset=raw` is a convenience workflow, not the canonical
paper run, because pairing it with a second peer-enabled study would duplicate
model execution.

### Which artifacts answer the core questions?

| Question | Canonical location |
| --- | --- |
| Design and claim contract | `docs/paper_plan.md` |
| Current figures, tables, and interpretations | `docs/results_snapshot.md` |
| Public task artifacts | `artifacts/full_with_peer/public_cascade/` |
| Bridge QA | `$DATA_DIR/linkage/raw_only/` |
| Construct alignment | `artifacts/full_with_peer/construct_overlap/` |
| Generated manuscript evidence | `artifacts/manuscript_package/` |
| Canonical validation and reviewer archive | `artifacts/canonical_validation/`, `artifacts/reviewer_package/` |
