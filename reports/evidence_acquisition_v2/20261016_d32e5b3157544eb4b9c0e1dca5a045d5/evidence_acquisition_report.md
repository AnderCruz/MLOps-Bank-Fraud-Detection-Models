# Evidence Acquisition v2 — Lifecycle and Traceability Corrections

- **Work package ID:** `evidence-acquisition-v2-20261016_d32e5b3157544eb4b9c0e1dca5a045d5`
- **Directory token:** `20261016_d32e5b3157544eb4b9c0e1dca5a045d5`
- **Versioned directory:** `reports/evidence_acquisition_v2/20261016_d32e5b3157544eb4b9c0e1dca5a045d5`
- **Source plan:** `reports/operational_planning_v2/20261016_85cd78147e3b41c0ba796f6c1d5d7d19/operational_planning.json` (`operational-planning-v2-20261016-85cd78147e3b41c0ba796f6c1d5d7d19`)
- **Package status:** `READY_WITH_GAPS`

## Scope and preservation

This package corrects lifecycle, traceability, role-boundary, and direct-linkage issues before outreach. All requests remain unsent. No new evidence was acquired; no dataset, test split, training, inference, scoring, metric calculation, or MLflow write occurred. Evidence Acquisition v1, M5, M6, and Operational Planning v2 are preserved unchanged. Roles are descriptive planning labels; no person or formal organizational appointment is asserted.

The historical v1 directory token and work-package identifier differed. V2 uses one identity across its directory, JSON, and Markdown. V1 JSON SHA-256: `cb48aebd9e00ac5479396ea36021c36358fd820035f4a17a30eda874aeea3b84`; v1 Markdown SHA-256: `ec4d997a1797b3b689f045c440262e040356e7dec57a12a482ef81cb70e54dba`.

## Changes from v1

- Retained STREQ-01 through STREQ-09 and added STREQ-10 (missed-fraud risk), STREQ-11 (customer experience), STREQ-12 (review capacity), and STREQ-13 (custodian cohort availability as supporting evidence only).
- Every request has direct planning-task and acquisition-task IDs. The traceability table is generated from those direct links.
- STREQ-01 now asks only about objective/action. STREQ-02 asks for the authorized population decision; STREQ-13 separately asks a custodian about possible availability and does not carry decision authority.
- STREQ-04 separates acceptance/calibration/confirmation from risk, customer-impact, and capacity questions and removes the unrelated OPS-07 update-cadence link.
- STREQ-07 explicitly asks about drift signals, interpretation, escalation criteria, and responsibilities.
- EVD-06, EVD-11, and EVD-13 use precise direct decision links; broader planning links are classified as downstream dependencies.

## Request lifecycle and traceability

| Request | State | Planning tasks | Acquisition tasks | Direct decisions |
|---|---|---|---|---|
| STREQ-01 — Operational objective and action | PREPARED; authorization PENDING; NOT SENT | TASK-01 | ACQ-02, ACQ-11 | DEC-OPS-01 |
| STREQ-02 — Target population and transaction eligibility decision | PREPARED; authorization PENDING; NOT SENT | TASK-14 | ACQ-03, ACQ-12 | DEC-OPS-12 |
| STREQ-03 — Fraud label provenance and maturity | PREPARED; authorization PENDING; NOT SENT | TASK-03 | ACQ-04, ACQ-13 | DEC-OPS-08 |
| STREQ-04 — Acceptance criteria, calibration, and decision authority | PREPARED; authorization PENDING; NOT SENT | TASK-05 | ACQ-05, ACQ-14 | DEC-OPS-13 |
| STREQ-05 — Data provenance and point-in-time feature availability | PREPARED; authorization PENDING; NOT SENT | TASK-04 | ACQ-06, ACQ-15 | DEC-OPS-08, DEC-OPS-11, DEC-OPS-12 |
| STREQ-06 — Service mode, workload, and engineering requirements | PREPARED; authorization PENDING; NOT SENT | TASK-09, TASK-15 | ACQ-07, ACQ-16 | DEC-OPS-05, DEC-OPS-06 |
| STREQ-07 — Model update governance, monitoring, and drift response | PREPARED; authorization PENDING; NOT SENT | TASK-10 | ACQ-08, ACQ-17 | DEC-OPS-07, DEC-OPS-09 |
| STREQ-08 — Incident response, fallback, and rollback | PREPARED; authorization PENDING; NOT SENT | TASK-12 | ACQ-09, ACQ-18 | DEC-OPS-10 |
| STREQ-09 — Security, privacy, retention, and audit | PREPARED; authorization PENDING; NOT SENT | TASK-13 | ACQ-10, ACQ-19 | DEC-OPS-11 |
| STREQ-10 — Missed-fraud risk constraints | PREPARED; authorization PENDING; NOT SENT | TASK-02 | ACQ-21, ACQ-22 | DEC-OPS-02 |
| STREQ-11 — False-positive and customer-experience constraints | PREPARED; authorization PENDING; NOT SENT | TASK-02 | ACQ-23, ACQ-24 | DEC-OPS-03 |
| STREQ-12 — Fraud review capacity and alert-handling workflow | PREPARED; authorization PENDING; NOT SENT | TASK-02 | ACQ-25, ACQ-26 | DEC-OPS-04 |
| STREQ-13 — Candidate cohort availability and coverage (custodian response) | PREPARED; authorization PENDING; NOT SENT | TASK-07 | ACQ-27, ACQ-28 | None; supporting request |

All 13 request templates have no sender attribution, authorization, sent timestamp, or dispatch reference. Response and review states remain pending.

## Lifecycle authority and transition rules

Each mutable stage has one authoritative field: request state in `stakeholder_request_templates[].request_status`; response state in `response.status`; review state in `review.status` (and separately on each evidence result); evidence acceptance in `evidence_results[].acceptance.state`; decision resolution in `decision_resolution_records[].resolution_status`. Acquisition-task status records workflow only and cannot imply an event or decision.

Allowed transitions are recorded in JSON. Requests move PREPARED → AUTHORIZED → SENT or may be cancelled before dispatch. Responses move PENDING → RECEIVED or NOT_PROVIDED, with late receipt permitted. Reviews may proceed from PENDING through IN_PROGRESS to ACCEPTED, REJECTED, or INCONCLUSIVE. Evidence acceptance requires completed, sufficient review and attributed authorization. A decision can be RESOLVED only through a distinct authorized decision-resolution record with outcome, rationale, time, and evidence references. No transition event is recorded as having happened.

A sent request must include authorized sender, timestamp, and dispatch reference. A received response must include respondent/source attribution, receipt time, source reference, and provenance, unless a documented exception is approved. Accepted evidence requires review, sufficiency rationale, approver attribution, time, and source/review references. Resolved decisions require a separately authorized decision record.

## Evidence-gap status and corrected direct links

All 13 evidence gaps remain OPEN; each acceptance state is NOT_ASSESSED. No evidence record is asserted as newly received or accepted. All 13 planning decisions remain OPEN with no resolution record.

| Gap | Direct decisions | Downstream decision dependencies |
|---|---|---|
| EVD-06 | DEC-OPS-07, DEC-OPS-09 | DEC-OPS-10 |
| EVD-11 | DEC-OPS-10 | DEC-OPS-01, DEC-OPS-02, DEC-OPS-03, DEC-OPS-04, DEC-OPS-05, DEC-OPS-06, DEC-OPS-07, DEC-OPS-08, DEC-OPS-09, DEC-OPS-11, DEC-OPS-12, DEC-OPS-13 |
| EVD-13 | DEC-OPS-13 | DEC-OPS-01, DEC-OPS-02, DEC-OPS-03, DEC-OPS-04, DEC-OPS-05, DEC-OPS-06, DEC-OPS-07, DEC-OPS-08, DEC-OPS-09, DEC-OPS-10, DEC-OPS-11, DEC-OPS-12 |

These package corrections do not edit Operational Planning v2. The original broader planning associations are retained in the JSON as `planning_source_related_decision_ids` for auditability.

## Evidence boundaries retained

- M5 policy v2 covers eight model families; all eight `quality_thresholds.*.value` entries remain null. All eight referenced M5 candidate assessments remain `INSUFFICIENT_EVIDENCE`.
- M6 does not establish an eligible, mature-label, independent confirmation cohort. The previously examined test split is not a fresh blind confirmation cohort.
- Validation metrics do not establish approved business objectives or acceptance criteria.
- `src/inference.py` documents an offline inference contract, not a production service or complete upstream data lineage.
- Repository inspection cannot establish whether additional organizational records exist elsewhere.
- No gap is closed merely because a report, document, template, response placeholder, or task exists. No threshold or new empirical claim was introduced.

## Remaining blockers

Formal assignment of requesters, senders, reviewers, approvers, and decision-makers is outstanding. Requests require authorization before dispatch. Responses need provenance; evidence requires substantive review before acceptance; decisions require separate authorization and evidence references. The operational objective, population/availability, label maturity, acceptance criteria, monitoring, service, incident, security, and independent-confirmation requirements remain unresolved.

## Validation and preservation

The package is subject to static JSON, link, lifecycle, transition, DAG, and Markdown checks only. No data or model workflow is invoked. V1 JSON/Markdown and Operational Planning v2 hashes are recorded in the package and checked by the automated test. No Git staging operation is performed.

Executed validation commands and results:

- `python3 -m unittest discover -s tests -p 'test_evidence_acquisition_v2.py' -v` — PASS, 8 tests.
- `python3 -m py_compile tests/test_evidence_acquisition_v2.py` — PASS.
- `python3 -m json.tool reports/evidence_acquisition_v2/20261016_d32e5b3157544eb4b9c0e1dca5a045d5/evidence_acquisition.json` — PASS.
- Static trailing-whitespace scan of new text files — PASS.
- `git diff --check` — PASS.
