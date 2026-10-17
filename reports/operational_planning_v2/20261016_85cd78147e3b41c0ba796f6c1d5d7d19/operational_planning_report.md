# Operational Planning v2 — Targeted Corrections

**Status:** `READY_WITH_GAPS`  
**Plan ID:** `operational-planning-v2-20261016-85cd78147e3b41c0ba796f6c1d5d7d19`  
**Version:** `2`  
**Source:** [v1 JSON](reports/operational_planning_v1/20261014_79b5ae69bf1944fb94b9e4abc98c0a61/operational_planning.json) and its companion report.  
**M6 evidence snapshot:** `reports/evidence_readiness_v1/62e68772501249cfb45ed3810758d365/evidence_readiness_report.json`  
**M5 policy:** `configs/validation_policy_v2.json`

## Purpose and change history

This version is a planning-register correction, not a new policy or evaluation protocol. It preserves v1 and its stable OPS-01–OPS-11, DEC-OPS-01–11, EVD-01–10, and TASK-01–11 identifiers. It adds explicit records for target population and acceptance requirements; makes every task independently actionable; separates monitoring/update, incident/fallback/rollback, and security responsibilities; and adds evidence-priority rationales and reciprocal links. New IDs are OPS-12–13, DEC-OPS-12–13, EVD-11–13, and TASK-12–15. Existing uncertainty and source status remain unresolved where evidence is absent.

## Current factual boundaries

- M5 policy v2 remains authoritative and unchanged. All eight numeric thresholds remain `null`; candidate readiness remains `INSUFFICIENT_EVIDENCE`.
- Supervised classifiers retain AP as the primary ranking measure. For Autoencoder, reconstruction MSE is the policy/checkpoint metric and anomaly-ranking AP is separate; reconstruction error is not a fraud probability.
- No qualifying independent cohort is confirmed. The previously examined test split is not an untouched or fresh blind confirmation cohort. No independent evaluation is claimed.
- Existing validation comparisons are selection-conditioned. There is no documented production service, no measured latency/throughput/memory/cost/review burden, and no approved operational objective.
- `source_known_to_exist=UNKNOWN` remains an uncertainty statement, not evidence that a source is available. Defining a task does not mean evidence has been acquired.

## Registers

The JSON register is authoritative for full field values and cross-references. The concise execution sequence is:

| Task | Owner role | Deliverable / closure condition | Status | Dependencies |
|---|---|---|---|---|
| TASK-01 — Decide operational objective and action mode | Fraud operations / product owner | Versioned objective/action decision for DEC-OPS-01, with scope, rationale, evidence references and approval status. Closure: Approved role decision is recorded with objective/action mode, rationale, scope, source evidence, version and approval state. | `STAKEHOLDER_DECISION_REQUIRED` | None |
| TASK-02 — Decide missed-fraud, false-positive/customer-impact, and review-capacity constraints | Fraud risk owner with fraud-operations owner | Versioned decisions for DEC-OPS-02 through DEC-OPS-04; numeric constraints only where an owner supplies and approves evidence-backed rationale. Closure: Each of DEC-OPS-02/03/04 has an accountable role decision or an explicit unresolved disposition with evidence and approval state; no unsupported numeric value is added. | `BLOCKED` | TASK-01 |
| TASK-03 — Establish label generation, maturity, unresolved-label handling and custody | Fraud data / label operations owner | Approved label provenance and maturity specification, including unresolved labels and evidence of the process/source. Closure: Authorized record specifies label generation/adjudication, maturity delay, unresolved-label handling, source/custody and effective version. | `STAKEHOLDER_DECISION_REQUIRED` | None |
| TASK-04 — Verify point-in-time feature availability, data lineage, deduplication/overlap and population representativeness | Data custodian / data governance owner | Feature/source lineage and cohort data-quality assessment covering point-in-time availability, duplication, overlap, custody and representativeness. Closure: Source and timing evidence exists for every feature used, duplicate/overlap rules and representativeness criteria are documented, and custodians attest the candidate cohort scope. | `BLOCKED` | TASK-03, TASK-14 |
| TASK-05 — Define acceptance metric interpretation and any separate calibration protocol | Fraud risk / product owner and model-risk owner | Versioned acceptance criteria decision distinguishing ranking measures, business constraints, calibration, independent confirmation and decision authority. Closure: Authorized, evidence-referenced decision states how supervised AP is used for ranking, how AE reconstruction MSE and anomaly AP remain distinct, what business gates apply, and whether calibration is needed; no unsupported thresholds are set. | `BLOCKED` | TASK-01, TASK-02, TASK-03, TASK-14 |
| TASK-06 — Approve a frozen evaluation manifest | Evaluation owner with model-risk approver | Versioned freeze manifest identifying candidate artifacts/hashes, metadata, features/scaler/inference, cohort rules, metric implementations, uncertainty/exclusions, policy and decision procedure. Closure: Required source identifiers/hashes and protocol fields are complete, reviewed and approved before any confirmation cohort is accessed. | `BLOCKED` | TASK-01, TASK-03, TASK-04, TASK-05, TASK-14 |
| TASK-07 — Qualify a disjoint, eligible cohort with mature labels | Data custodian and fraud-label operations owner | Custodian-backed cohort qualification record: eligibility, boundaries, maturity, disjointness, extraction/custody, availability and approved access. Closure: A distinct cohort is evidenced as available, eligible, disjoint from development/selection/calibration, and mature under the approved label policy; authorized access is recorded. | `BLOCKED` | TASK-03, TASK-04, TASK-06, TASK-14 |
| TASK-08 — Run controlled independent confirmation and record acceptance disposition | Evaluation owner; disposition by authorized risk/model governance role | Reproducible independent-evaluation report and signed/versioned acceptance disposition under the frozen policy. Closure: Execution follows the frozen protocol on the separately qualified cohort; report includes lineage, cohort, uncertainty, metric results and authorized disposition without post-hoc threshold/candidate changes. | `BLOCKED` | TASK-05, TASK-06, TASK-07 |
| TASK-09 — Define service mode, workload profile and service targets | Platform / service owner with fraud operations | Versioned service/workload profile covering inference mode, latency/availability needs, traffic and peak patterns, and required operational interfaces. Closure: Owners document workload and service targets with source evidence or explicitly record unknowns and the evidence needed; no unmeasured values are presented as facts. | `STAKEHOLDER_DECISION_REQUIRED` | TASK-01 |
| TASK-10 — Specify model update governance and production monitoring | Model operations owner with model-risk owner | Versioned monitoring/update plan: signals and label-delay treatment, owners, alert/escalation, update triggers/approval and runbooks. Closure: Authorized plan defines monitoring responsibility, measures/limitations, label delay, alert escalation, update triggers and approvals; unknown signals remain explicit. | `BLOCKED` | TASK-03, TASK-09 |
| TASK-11 — Make the production approval decision | Authorized production/model-risk governance authority | Versioned approve/defer/reject record citing independent confirmation, service benchmark, monitoring, failure and security evidence; no approval is presumed. Closure: Authorized decision explicitly approves, defers or rejects with rationale and evidence references; missing prerequisites result in defer/blocked rather than inferred approval. | `BLOCKED` | TASK-08, TASK-10, TASK-12, TASK-13, TASK-15 |
| TASK-12 — Define incident, failure, fallback and rollback behavior | Service owner with fraud operations and model operations | Versioned failure-mode, fallback/degraded-mode, escalation, rollback authority/trigger and recovery runbook. Closure: Authorized runbook identifies failure conditions, safe behavior, fallback, rollback authority/triggers, escalation and recovery; required review is recorded. | `BLOCKED` | TASK-01, TASK-09 |
| TASK-13 — Specify security, privacy, retention and audit controls | Security / privacy / compliance owner | Applicable control assessment and approved access, privacy/legal basis, retention/deletion and audit requirements. Closure: Authorized assessment cites applicable requirements and records controls, owners, evidence, exceptions and approval state. | `STAKEHOLDER_DECISION_REQUIRED` | None |
| TASK-14 — Define intended target population, transaction eligibility and exclusions | Fraud product / risk owner with data custodian | Versioned population/eligibility decision with exclusions and rationale, deployment-context relation, and a separate availability/coverage assessment. Closure: Authorized population definition and custodian assessment specify eligible transactions, exclusions/rationale, deployment relation and whether an appropriate cohort is evidenced as available. | `STAKEHOLDER_DECISION_REQUIRED` | None |
| TASK-15 — Benchmark frozen candidates against agreed service/workload requirements | Platform/service owner with evaluation owner | Reproducible benchmark report for frozen candidate configurations against approved workload/service profile, including environment and measurement method. Closure: Repeatable measurements cover approved workload, candidates and environment, with methods/uncertainty and limitations recorded; no synthetic or assumed service target is substituted. | `BLOCKED` | TASK-06, TASK-09 |

### Explicit stakeholder decisions

- `DEC-OPS-12` asks authorized roles to define intended population, eligibility, exclusions and rationale, and the relationship to deployment. It does not select a population for them.
- `DEC-OPS-13` separates ranking/comparative metrics, business acceptance criteria, false-positive/review constraints, calibration, independent confirmation and production approval. It does not set unsupported cutoffs.
- The original `DEC-OPS-01`–`DEC-OPS-11` remain open at their source statuses, with decision-specific options, consequences, needed evidence, and deferral impacts in JSON. No recommendation is represented as approved.

### Evidence priorities

All EVD-01–EVD-10 priorities are retained. Each gap now has a `priority_rationale`. EVD-11 shares priority 6 with other governance work; EVD-12 shares priority 2 with label maturity; EVD-13 shares priority 4 with acceptance criteria. Lower numbers indicate earlier evidence-enabling work; ties are parallel tiers, not precedence claims. Status and source-availability fields distinguish known project evidence, requests, not-yet-available evidence, and unknown sources.

### Task sequencing and blocked stages

The task graph is directed and acyclic. Population definition and label maturity can start independently. Feature/data provenance requires label and population context. Acceptance follows objective, constraints, label, and population inputs; protocol freeze follows acceptance and provenance. Cohort qualification requires a frozen protocol; independent confirmation requires a qualified cohort. Service profile precedes measurement; monitoring and incident controls are separate workstreams; security review can proceed independently. Production approval is downstream of confirmation, benchmark, monitoring, incident controls and security.

## Still open

All original OPS-01–OPS-11 source statuses remain `UNKNOWN_NOT_DOCUMENTED`; their planning status is not an approval. OPS-12 and OPS-13 are new planning questions and also remain unknown. Stakeholders have not supplied decisions. Evidence sources and a suitable cohort remain unverified. No evidence acquisition or outreach occurred in this phase.

## Readiness

**`READY_WITH_GAPS`** — the planning register is actionable, but decisions, evidence, a qualifying cohort, thresholds, service measurements and governance controls remain open. Initial stakeholder requests and evidence-source discovery may begin. Threshold calibration, independent confirmation and production approval remain blocked until their listed prerequisites are satisfied.
