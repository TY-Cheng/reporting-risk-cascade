---
hide:
  - navigation
---

# Deferred Extensions

This page records the research program after the current benchmark plus public
cascade paper. These extensions are deliberately deferred so the main study does
not become an overextended data-engineering exercise before the measurement
spine is stable.

!!! warning "Scope guardrail"
    The current paper must first keep label-observability diagnostics, concept
    drift, public-label opacity analysis, full public-lake construction, public
    cascade prediction, and `gvkey-CIK-year` overlap validation reproducible.
    Future models should be added only after those foundations are stable.

[Back to the current paper plan](paper_plan.md){ .md-button .md-button--primary }
[Return to docs home](index.md){ .md-button }

<div class="grid cards" markdown>

- :material-text-box-search-outline: __Multimodal cascade__

    ---

    Add filing text only after the structured public cascade and lead-time baselines
    are stable.

- :material-finance: __Attention and market layers__

    ---

    Add 13F, EDGAR-log, FTD, and market-structure inputs only after temporal
    security bridges and source-availability masks are defensible. SEC Insider
    Transactions are a narrower P1 issuer-CIK extension in the current paper plan,
    not part of this security-level expansion.

- :material-account-network-outline: __Auditor and oversight network__

    ---

    Expand Form AP and PCAOB structure into network-style monitoring exposure only
    after issuer-auditor joins are reliable.

- :material-alert-decagram-outline: __Richer detector labels__

    ---

    Move toward occurrence-detection-disclosure decomposition only when stronger
    external restatement timing and detector data exist.

</div>

=== "Near-Term Preconditions"

    - Finish the current benchmark plus public-cascade paper.
    - Validate gold-panel readiness and overlap diagnostics.
    - Promote only one extension family at a time.

=== "Deferred Until"

    - Text and graph models have a clearly defined incremental estimand.
    - Security-level data can be linked through documented temporal bridges.
    - Additional channels strengthen, rather than dilute, the current measurement claim.

## Extension Portfolio

| Extension | Research contribution | When to activate |
| --- | --- | --- |
| Multimodal cascade | Test whether narrative filings add lead time and stage-specific information. | After public cascade labels are stable. |
| Public security and attention layers | Add institutional, attention, FTD, and market microstructure channels. | After temporal security-to-CIK bridges are available. |
| Auditor and oversight network | Model monitoring exposure through Form AP, partners, firms, and PCAOB inspections. | After Form AP and inspection joins are clean. |
| Severity and detector labels | Move toward occurrence-detection-disclosure decomposition. | After higher-quality restatement or detector data are acquired. |
| Reproducibility package | Make the empirical pipeline submission-ready. | Before manuscript circulation and review. |

## Extension 1: Multimodal Cascade Model

Working title:

__Narrative and Monitoring Signals in the Public Reporting-Risk Cascade__

Alternative title:

__Occurrence, Detection, Disclosure: A Multimodal Graph of Corporate Reporting Risk__

### Research Question

Do structured filings, narrative disclosures, auditor/partner monitoring networks,
and public enforcement events load on different stages of the public reporting-risk
cascade?

The key hypothesis is stage separation:

- 10-K narrative changes should help earlier, pre-disclosure risk states.
- auditor and oversight variables should matter more for public scrutiny and correction.
- 8-K Item 4.02 framing should help explain downstream severity proxy outcomes.

### Incremental Data

Start from the full public-cascade lake and add raw filing text:

- raw 10-K and 10-K/A filing HTML
- raw 8-K and 8-K/A filing HTML
- parsed Item 1A Risk Factors
- parsed Item 7 MD&A
- parsed 8-K Item 4.02 disclosure text
- amendment exhibit text when available

Then add graph/document nodes:

- issuer nodes
- filing nodes
- Form AP auditor and partner nodes
- PCAOB inspection nodes
- public comment-thread nodes
- correction-event nodes
- AAER proxy event nodes

Optional later sources:

- 13F institutional-holder features
- insider transactions
- EDGAR log attention measures
- market-structure data
- supplier-customer links

### Model Design

Use a staged architecture rather than a single undifferentiated text-plus-tabular
classifier:

- occurrence-risk proxy head: XBRL and 10-K narrative signals
- public scrutiny head: comment-letter and monitoring features
- correction head: amendment and 8-K Item 4.02 labels
- severity proxy head: AAER proxy and disclosure-framing labels

Candidate model families:

- multi-task tabular plus text model
- discrete-time multi-state hazard model
- temporal heterogeneous document graph

### Text Strategy

CPU-first phase:

- parse sections deterministically
- compute length, readability, dictionary, tone, and revision features
- compute compact embeddings on a filtered subset
- prove incremental lead time before scaling

GPU phase:

- use long-context finance embeddings for Item 1A and Item 7
- embed 8-K Item 4.02 disclosure text for framing and severity labels
- run full-corpus embedding only after the CPU-first phase shows value

### Acceptance Criteria

This extension should not be judged by aggregate PR-AUC alone. It needs
stage-specific evidence:

- text adds lead time for distant-horizon risk
- auditor and oversight variables matter more for scrutiny/correction stages
- 8-K framing predicts downstream severity proxy
- graph features represent monitoring exposure, not untested contagion

### Implementation Status

No runtime code is retained for this extension. The old multimodal prototype was
removed so the active codebase stays focused on benchmark, public cascade, and the
combined study workflow.

When this extension becomes active again, implement it as a new module rather than
reintroducing it into the current study path.

## Extension 2: Public Security and Attention Layers

### Research Question

Do public capital-market attention and ownership structures predict which reporting
risk states become publicly visible?

This extension should not be framed as "market variables improve prediction" in a
generic way. The research mechanism is public visibility: institutional holdings,
insider trading, attention, and liquidity may change the probability that reporting
problems are scrutinized, corrected, or escalated.

### Candidate Sources

- SEC 13F datasets
- SEC insider transactions datasets
- SEC EDGAR log datasets
- SEC market-structure datasets

### Identity Challenge

These sources are not naturally `CIK` native. They require a temporal bridge across:

- `CIK`
- ticker
- CUSIP
- accession/adsh
- reporting manager identifiers
- security-level market structure identifiers

Every mapping must carry provenance and validity windows. A current ticker-to-CIK
lookup is not enough for a historical panel.

### Potential Features

- institutional ownership concentration
- institutional turnover
- transient versus dedicated holder exposure
- insider sale pressure
- filing-attention shocks
- liquidity and spread changes
- market microstructure stress before public correction events

### Acceptance Criteria

- every security-level source must retain its original security key
- no ticker or CUSIP should be coerced into CIK without a documented mapping table
- feature availability masks must distinguish source non-existence from issuer silence
- attention and liquidity variables must be timestamped strictly before `origin_date`

## Extension 3: Auditor and Oversight Network

### Research Question

Does public monitoring exposure through auditors, partners, and PCAOB inspections
help explain public scrutiny and correction outcomes?

The mechanism is monitoring and lagged public exposure, not a causal contagion
claim. The design should ask whether public oversight networks reveal where
reporting-risk states are more likely to become visible.

### Network Nodes

- issuer
- audit firm
- audit office, if available
- engagement partner
- other audit participants
- PCAOB inspection report
- inspection deficiency type
- correction event
- comment-thread event

### Candidate Features

- partner-level public workload
- partner prior correction exposure
- audit-firm inspection deficiency history
- issuer exposure to recently inspected audit firms
- peer correction exposure within the same audit firm or partner network
- auditor turnover and monitoring discontinuity

### Guardrails

- do not frame this as contagion unless the design separates common shocks,
  monitoring intensity, and network exposure
- do not treat partner or firm exposure as causal without a credible design
- keep network variables in the monitoring channel first, not in a general-purpose
  graph black box

## Extension 4: Restatement Severity And Detector Labels

### Research Question

Can the public cascade be upgraded into a richer occurrence-detection-disclosure
decomposition once stronger external labels are available?

### Data Requirements

If paid or higher-quality data become available, add:

- restatement filing dates
- affected period start and end dates
- severity categories
- fraud indicators
- detector or notifier identity
- SEC comment-letter/enforcement linkage
- restatement magnitude and account categories

### Potential Contribution

This extension would move from public cascade prediction toward
occurrence-detection-disclosure decomposition. The conceptual payoff is large, but
the identification burden is also much higher.

### Guardrails

- do not put bivariate-probit or partial-observability identification in the main
  model unless there are defensible exclusion restrictions or detector-side variables
- do not call public correction labels true latent occurrence
- keep detector labels separate from severity labels

## Extension 5: Reproducibility Package

Before submission, build a reproducibility package that is separate from exploratory
development.

### Required Contents

- pinned data as-of date
- source manifests and SHA256 hashes
- parser versions
- row-count reports for bronze, silver, and gold layers
- model configuration files
- table and figure reproduction commands
- smoke-data test path for reviewers without public downloads
- documentation build command

### Reproducibility Command Shape

```bash
just status
just task study raw artifacts/study
just docs
```

The full public-data download should remain a separate long-running operational job
because it is network dependent.

### Submission Criteria

- a fresh clone with `.env` configured can build docs and run tests
- smoke data can reproduce the pipeline shape without the full public lake
- full results can be regenerated from raw public sources and local manifests
- every table in the manuscript maps to a single artifact path
