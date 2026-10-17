# Evidence Acquisition & Stakeholder Request Work Package

**Status:** `PREPARATION_COMPLETE_EXTERNAL_EVIDENCE_PENDING`
**Work package ID:** `evidence-acquisition-v1-20261016-c98380a6fe0c41f7b55765b9af81c850`
**Versioned directory:** `reports/evidence_acquisition_v1/20261016_c048f5dba2834c66b484dfc6b958880a/`
**Source of truth:** Operational Planning v2 `operational-planning-v2-20261016-85cd78147e3b41c0ba796f6c1d5d7d19` at `reports/operational_planning_v2/20261016_85cd78147e3b41c0ba796f6c1d5d7d19/operational_planning.json`.
**Requests:** Draft templates only; all are `NOT_SENT`.

## Purpose and boundaries

This package records evidence located in the repository, what each source does and does not establish, open information needs, unsent stakeholder request templates, and the next acquisition tasks. Repository absence is not evidence that a document or source does not exist elsewhere. No external evidence was requested or acquired. No dataset content was inspected, including no test-split content.

## Evidence availability by planning gap

| Gap | Availability | Located project evidence | What remains open |
|---|---|---|---|
| EVD-01 | `AVAILABLE_PARTIAL` | `reports/validation_evaluation_1d24658eef4f4241b4f4e4c1e3a00578.json`, `reports/validation_analysis/operational_feasibility_v1/1d24658eef4f4241b4f4e4c1e3a00578/a3d9952ae0f44206a6b4f1e20c372a5d/operational_feasibility_report.json`, `reports/evidence_readiness_v1/62e68772501249cfb45ed3810758d365/evidence_readiness_report.json` | Fraud objective and risk/capacity decisions remain stakeholder-dependent. |
| EVD-02 | `STAKEHOLDER_INPUT_REQUIRED` | `reports/evidence_readiness_v1/62e68772501249cfb45ed3810758d365/evidence_readiness_report.json`, `reports/operational_planning_v2/20261016_85cd78147e3b41c0ba796f6c1d5d7d19/operational_planning.json` | Label source, adjudication, maturity delay, unresolved-label policy, observation window and custody are unknown. |
| EVD-03 | `AVAILABLE_PARTIAL` | `src/inference.py`, `reports/validation_analysis/1d24658eef4f4241b4f4e4c1e3a00578/d034e61aaf394581ab9ffb8e3c471089/analysis_manifest.json`, `reports/evidence_readiness_v1/62e68772501249cfb45ed3810758d365/evidence_readiness_report.json` | Authoritative feature-source attestations and future-cohort extraction/custody evidence are not established. |
| EVD-04 | `AVAILABLE_PARTIAL` | `configs/validation_policy_v2.json`, `reports/validation_policy_analysis_v1/8f76ffc6bfb6420dbbe90b4a37de1579/policy_analysis.json`, `reports/validation_evaluation_1d24658eef4f4241b4f4e4c1e3a00578.json`, `reports/evidence_readiness_v1/62e68772501249cfb45ed3810758d365/evidence_readiness_report.json` | No approved business acceptance rule, justified threshold, calibration cohort/method, or authorized decision procedure is established. |
| EVD-05 | `NOT_AVAILABLE_IN_REPOSITORY` | `README.md`, `src/inference.py`, `reports/evidence_readiness_v1/62e68772501249cfb45ed3810758d365/evidence_readiness_report.json` | Traffic volume/peaks, latency/throughput, availability, deployment mode and resource/cost requirements remain unknown. |
| EVD-06 | `STAKEHOLDER_INPUT_REQUIRED` | `reports/evidence_readiness_v1/62e68772501249cfb45ed3810758d365/evidence_readiness_report.json`, `reports/operational_planning_v2/20261016_85cd78147e3b41c0ba796f6c1d5d7d19/operational_planning.json` | Monitoring measures, owners, label-delay treatment, alerting/escalation and update triggers/approval remain unknown. |
| EVD-07 | `STAKEHOLDER_INPUT_REQUIRED` | `reports/evidence_readiness_v1/62e68772501249cfb45ed3810758d365/evidence_readiness_report.json`, `reports/operational_planning_v2/20261016_85cd78147e3b41c0ba796f6c1d5d7d19/operational_planning.json` | Legal basis, data classification, access control, retention/deletion, audit and compliance obligations remain unknown. |
| EVD-08 | `AVAILABLE_PARTIAL` | `reports/validation_evaluation_1d24658eef4f4241b4f4e4c1e3a00578.json`, `reports/validation_analysis/1d24658eef4f4241b4f4e4c1e3a00578/d034e61aaf394581ab9ffb8e3c471089/analysis_manifest.json`, `configs/validation_policy_v2.json`, `reports/evidence_readiness_v1/62e68772501249cfb45ed3810758d365/evidence_readiness_report.json` | Future candidate hashes, cohort eligibility, exclusions, acceptance rules, uncertainty method and decision procedure require authorized freeze. |
| EVD-09 | `BLOCKED_BY_DEPENDENCY` | `reports/evidence_readiness_v1/62e68772501249cfb45ed3810758d365/evidence_readiness_report.json`, `reports/operational_planning_v2/20261016_85cd78147e3b41c0ba796f6c1d5d7d19/operational_planning.json` | A later/disjoint or independently governed eligible population with mature labels, custody and authorized access is unconfirmed. |
| EVD-10 | `BLOCKED_BY_DEPENDENCY` | `reports/validation_evaluation_1d24658eef4f4241b4f4e4c1e3a00578.json`, `reports/evidence_readiness_v1/62e68772501249cfb45ed3810758d365/evidence_readiness_report.json`, `reports/operational_planning_v2/20261016_85cd78147e3b41c0ba796f6c1d5d7d19/operational_planning.json` | Frozen independent results, uncertainty and authorized acceptance disposition do not exist in the inspected project sources. |
| EVD-11 | `STAKEHOLDER_INPUT_REQUIRED` | `reports/evidence_readiness_v1/62e68772501249cfb45ed3810758d365/evidence_readiness_report.json`, `reports/operational_planning_v2/20261016_85cd78147e3b41c0ba796f6c1d5d7d19/operational_planning.json` | Failure modes, safe behavior, fallback/degraded mode, rollback triggers/authority, incident escalation and recovery are unknown. |
| EVD-12 | `UNKNOWN_SOURCE_AVAILABILITY` | `reports/evidence_readiness_v1/62e68772501249cfb45ed3810758d365/evidence_readiness_report.json`, `reports/operational_planning_v2/20261016_85cd78147e3b41c0ba796f6c1d5d7d19/operational_planning.json` | Target population, eligibility/exclusions, deployment-context relationship and data availability/representativeness remain unknown. |
| EVD-13 | `AVAILABLE_PARTIAL` | `configs/validation_policy_v2.json`, `reports/validation_policy_analysis_v1/8f76ffc6bfb6420dbbe90b4a37de1579/policy_analysis.json`, `reports/evidence_readiness_v1/62e68772501249cfb45ed3810758d365/evidence_readiness_report.json`, `reports/operational_planning_v2/20261016_85cd78147e3b41c0ba796f6c1d5d7d19/operational_planning.json` | Metric roles, business acceptance criteria, threshold/calibration need, independent confirmation criteria and decision authority remain open. |

### Interpretation

- Existing validation reports, manifests and analysis artifacts are available as project evidence, but they remain selection-conditioned and do not establish business requirements or independent confirmation.
- M5 policy v2 remains authoritative. Numeric thresholds remain null. Supervised AP remains the ranking metric; Autoencoder reconstruction MSE is distinct from AP over reconstruction-error anomaly scores. The anomaly score is not a fraud probability.
- M6 reports no qualifying independent cohort confirmed. The previously examined test split is not a fresh blind confirmation cohort.
- No availability claim is made for organizational records beyond the repository search scope.

## Prepared stakeholder requests

| Request | Intended recipient roles | Linked decisions | Status |
|---|---|---|---|
| STREQ-01 — Operational objective, risk and review constraints | Fraud operations / product owner, Fraud risk owner, Fraud operations / customer experience owner | DEC-OPS-01, DEC-OPS-02, DEC-OPS-03, DEC-OPS-04 | `NOT_SENT` |
| STREQ-02 — Target population and transaction eligibility | Fraud product / risk owner, Data custodian | DEC-OPS-12, DEC-OPS-08 | `NOT_SENT` |
| STREQ-03 — Fraud label provenance and maturity | Fraud data / label operations owner, Data custodian | DEC-OPS-08 | `NOT_SENT` |
| STREQ-04 — Acceptance criteria, calibration and decision authority | Fraud risk / product owner, Model-risk owner, Fraud operations owner | DEC-OPS-13, DEC-OPS-01, DEC-OPS-02, DEC-OPS-03, DEC-OPS-04, DEC-OPS-07 | `NOT_SENT` |
| STREQ-05 — Data provenance and point-in-time feature availability | Data custodian, Data governance owner | DEC-OPS-12, DEC-OPS-08, DEC-OPS-11 | `NOT_SENT` |
| STREQ-06 — Service mode, transaction workload and engineering targets | Platform / service owner, Data / platform owner, Fraud operations owner | DEC-OPS-05, DEC-OPS-06 | `NOT_SENT` |
| STREQ-07 — Model update governance and monitoring | Model operations owner, Model-risk owner | DEC-OPS-07, DEC-OPS-09 | `NOT_SENT` |
| STREQ-08 — Incident response, fallback and rollback | Service owner, Fraud operations owner, Model operations owner | DEC-OPS-10 | `NOT_SENT` |
| STREQ-09 — Security, privacy, retention and audit requirements | Security owner, Privacy/compliance owner | DEC-OPS-11 | `NOT_SENT` |

Templates are in `stakeholder_request_templates` in the JSON register. They contain no individual names, addresses, deadlines, or assumed organizational units. They are not evidence of outreach or approval.

## Execution order

1. `ACQ-01` repository-scope inventory is complete; this closes only the documentation-search action, not any planning evidence gap.
2. `ACQ-02`–`ACQ-10` request templates are prepared but unsent. Requester roles are unassigned in the planning source; an authorized role must be designated before routing. Drafting does not close any task.
3. `ACQ-11`–`ACQ-19` are response-specific evidence-intake tasks. Each is blocked until its corresponding request is sent and a response or source is provided; reviewer-role assignment is not established.
4. `ACQ-20` cohort availability assessment is blocked until population, label maturity and data-provenance responses are reviewed. This package does not authorize data extraction.

The JSON register contains per-task prerequisites, dependencies, outputs, closure conditions, statuses and blocked stages. It also contains a pending result placeholder for each EVD gap; every placeholder has `verified=false` and status `PENDING`.

## Remaining blockers

- Objective, risk, false-positive and review-capacity decisions remain unresolved.
- Target population, eligibility/exclusions and data availability remain unverified.
- Label provenance and maturity remain unknown.
- Acceptance criteria and any calibration requirement remain unresolved; no thresholds are proposed.
- Service/workload, monitoring, incident/rollback, security/privacy requirements remain unresolved or unverified.
- Independent confirmation remains blocked until a disjoint eligible mature-label cohort and frozen protocol are verified. Production approval remains downstream of independent evidence and operational/governance evidence.

No model selection, threshold decision, new metric calculation, independent evaluation, training or inference was performed.
