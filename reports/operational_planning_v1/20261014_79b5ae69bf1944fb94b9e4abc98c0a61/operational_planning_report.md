# Operational Requirements and Evidence Acquisition Plan

**Plan ID:** `20261014_79b5ae69bf1944fb94b9e4abc98c0a61`  
**Status:** Planning complete; requirements unapproved and evidence not acquired.

## Purpose and current state

This versioned plan expands the latest M6 register into traceable requirement, decision, evidence-gap, and task identifiers. It reuses M5 policy v2 and the M6 independent-evaluation design. It does not approve requirements, acquire evidence, define thresholds, evaluate models, or authorize production.

The latest M6 source is [`reports/evidence_readiness_v1/62e68772501249cfb45ed3810758d365/evidence_readiness_report.json`](../../evidence_readiness_v1/62e68772501249cfb45ed3810758d365/evidence_readiness_report.json). Its 11 open operational questions retain IDs OPS-01 through OPS-11 and original status `UNKNOWN_NOT_DOCUMENTED` in the `source_status` field; this plan maps them to the controlled planning status `UNKNOWN` without resolving them. It records zero documented operational requirements and zero measured operational evidence.

M5 v2 remains incomplete: thresholds are null for all eight families, and M5 candidate decisions remain `INSUFFICIENT_EVIDENCE`. Supervised families use validation AP as the primary ranking metric. Autoencoder reconstruction MSE is its checkpoint metric; anomaly-score AP is a separate ranking measure, not a probability.

## Actionable registers

The machine-readable record [`operational_planning.json`](operational_planning.json) contains:

- Requirements `OPS-01`–`OPS-11`, with owner roles, current/source status, blockers, missing evidence, and closure conditions.
- Decisions `DEC-OPS-01`–`DEC-OPS-11`. Suggested options are explicitly recommendations and remain unapproved.
- Evidence gaps `EVD-01`–`EVD-10`, prioritized by dependencies, with acquisition methods, sources, ownership, status, expected output, closure condition, and flags for stakeholder input/new data/controlled experiments.
- Execution tasks `TASK-01`–`TASK-11` and parallel workstreams. Dependencies point to task IDs and order the work without assigning dates.

Evidence source availability is marked `UNKNOWN` when no repository evidence proves the source exists. `REQUEST_REQUIRED` and `NOT_YET_AVAILABLE` describe open acquisition work; no task is represented as completed.

## Dependency sequence

Operational objective and risk/review constraints precede acceptance requirements. Label maturity and population availability can proceed in parallel with initial stakeholder decisions. Provenance and point-in-time feature availability depend on identifying a candidate source. Acceptance/calibration decisions and the evaluation freeze follow those prerequisites. Independent confirmation requires the frozen protocol and a separate eligible mature-label cohort. Production approval additionally requires service feasibility, monitoring, rollback, security/privacy, and an authorized acceptance decision.

Immediate work is limited to stakeholder requests and source/data-availability discovery (TASK-01, TASK-03, TASK-09, TASK-10). Threshold calibration, independent confirmation, and production approval remain blocked. No future data period or operational target is assumed.

## Threshold and evaluation readiness

Per-family readiness is in `threshold_definition_readiness.model_families`; it reuses the M5 metric/policy semantics without changing the policy. Existing evidence supports exploratory comparisons with caveats only. It does not support threshold definition or calibration, independent confirmation, or production approval. The previously examined test split is not a fresh blind confirmation cohort.

The independent-evaluation prerequisites reuse M6's protocol and explicitly require objective approval, target population and mature labels, provenance and feature availability, frozen artifacts and code, prespecified metrics/comparisons/uncertainty, separate calibration when needed, and validity/reporting/decision rules. No independent evaluation has occurred.

## Updating this plan

Future updates should preserve IDs, append or version decision/evidence records, cite source artifacts, and record owner/approval status. A proposed decision must not become a verified requirement without supporting approval evidence. Update status only when the stated acceptance condition is met; create a new versioned output rather than overwriting this record. Do not add numerical requirements without an approved, evidence-backed rationale.
