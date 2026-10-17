# Evidence Acquisition v3 — Lifecycle and Audit History

**Package:** `reports/evidence_acquisition_v3/20261016_c781f422ed224c2ba323b0ce53d0cc13/evidence_acquisition.json`  
**Validator:** `src/evidence_lifecycle.py`  
**Focused tests:** `tests/test_evidence_lifecycle.py`  
**Package status:** `READY_WITH_GAPS`

## Purpose and change from v2

Version 3 turns lifecycle policy into executable transition checks and preserves v2's 13 request IDs, 13 evidence-gap IDs, acquisition-task IDs, and decision IDs. It removes the redundant request-level `status` field; `request_status` is the only authoritative request-preparation state. The package is a new version; v1, v2, Operational Planning v2, M5, and M6 remain historical inputs and were not edited.

The v3 traceability records now explicitly separate `direct_related_requirement_ids`, `downstream_requirement_dependency_ids`, `direct_related_decision_ids`, and `downstream_decision_dependency_ids`. In particular, EVD-06 directly links OPS-07/OPS-09 and DEC-OPS-07/DEC-OPS-09, with OPS-10 and DEC-OPS-10 downstream; EVD-11 and EVD-13 retain their own direct and downstream distinctions in the JSON. Trace rows are checked against the evidence-gap records and all request/task references. During validation, the EVD-02, EVD-03, EVD-04, EVD-09, and EVD-12 trace rows were corrected to include every acquisition task that actually references each gap.

## Authoritative state fields

- Request preparation: `stakeholder_request_templates[].request_status` (`PREPARED`, `AUTHORIZED`, `CANCELLED`). No legacy duplicate `status` is accepted.
- Authorization: `stakeholder_request_templates[].authorization.status` (`PENDING`, `AUTHORIZED`, `DENIED`); no duplicate top-level authorization field is retained.
- Dispatch: `stakeholder_request_templates[].dispatch.status` (`NOT_SENT`, `SENT`, `CANCELLED`).
- Response: `stakeholder_request_templates[].response_status`; the current response is identified by `current_response_version_id` into `response_versions`.
- Review: `evidence_results[].review_status`; versioned review records and `current_review_version_id` live on that evidence result. A request can relate to multiple gaps, so request templates do not duplicate review state.
- Evidence acceptance: `evidence_results[].acceptance_status`; versions and the current pointer are `acceptance_versions` and `current_acceptance_id`.
- Decision resolution: `decision_resolution_records[].resolution_status`; records and pointer are `resolution_records` and `current_resolution_record_id`.
- History: `lifecycle_events`, replayed from `history_initial_states` and per-record initial states. Materialized current states must match replay.

## Enforced transitions and prerequisites

The validator rejects transitions outside the following lifecycle paths (explicit correction events are handled separately):

- Request: `PREPARED → AUTHORIZED` or `CANCELLED`; `AUTHORIZED → CANCELLED`. Authorization requires an identified request-specific authorization record, authorized-by attribution, and a timezone-aware timestamp. A denial is recorded in the authorization domain and cannot enable dispatch. Cancellation requires a reason and is limited to requests not yet sent.
- Authorization: `PENDING → AUTHORIZED` or `DENIED`. A terminal authorization cannot be silently replaced.
- Dispatch: `NOT_SENT → SENT` or `CANCELLED`. Sending requires the request to be authorized, the authorization record to exist, and dispatch ID/reference, sender, and timestamp. A sent request cannot use the pre-dispatch cancellation path.
- Response: `PENDING → RECEIVED` or `NOT_PROVIDED`; `NOT_PROVIDED → RECEIVED`. Receipt requires an actually sent request, respondent and received timestamp, source references, and `VERIFIED` provenance; an explicit documented exception is allowed and remains visible. `NOT_PROVIDED` requires an attributed, timestamped disposition and reason.
- Review: `PENDING → IN_PROGRESS → ACCEPTED`, `REJECTED`, or `INCONCLUSIVE`; `INCONCLUSIVE → IN_PROGRESS`. Starting review requires a current response. Completion requires the current response version, reviewer, timestamp, outcome, sufficiency assessment, rationale, and source references. An accepted outcome must be assessed `SUFFICIENT`.
- Acceptance: `NOT_ASSESSED → ACCEPTED`, `PARTIAL`, or `REJECTED`; `PARTIAL → ACCEPTED` or `REJECTED`. Acceptance requires a current accepted/sufficient review, an acceptance record citing that review, rationale, approver, timestamp, and sources. Partial/rejected dispositions are separately recorded with rationale/references and cannot turn a rejected or inconclusive review into accepted evidence. Acceptance never resolves a decision.
- Resolution: `OPEN → RESOLVED`. Resolution requires a separate resolution record, explicit authorized status and authorization attribution/timestamp, decision-maker, outcome, rationale, supporting evidence references, and event attribution.

Invalid transitions, missing prerequisites, contradictory states, stale pointers, duplicate IDs, and history replay mismatches raise `LifecycleValidationError` with an actionable message.

## History, correction, and supersession

Lifecycle functions return deep-copied records plus a new event list; the caller must persist each new package version and retain the previous one. Events contain IDs, entity/domain/type, prior/resulting states, actor, timestamp, supporting references, and (for corrections) a superseded event and reason. Event replay checks unique IDs, known entities/domains, matching previous states, timezone-aware timestamps, per-entity chronological order, permitted transitions, and correction references.

Response, review, and acceptance versions are retained in ordered supersession chains. Current pointers must identify the latest version. A response correction requires the current version and its receipt event to be explicitly superseded, with a reason and an explicit materiality declaration. The materiality value is stored on the replacement response version. For a material correction, package validation rejects any linked current review that does not cite the corrected response version. Prior acceptances can be explicitly invalidated, retaining their records and clearing the active pointer; a new acceptance requires a new qualifying review and acceptance. Review corrections reopen a completed review through an explicit correction event and retain the prior review. Resolution records are not silently overwritten.

These are append-only **application semantics**, not storage-level immutability. JSON files remain editable; no WORM store, digital signature, access-control integration, or cryptographic hash chain is implemented.

## Traceability rules

- Every request's planning-task and acquisition-task references must exist; its evidence-gap and decision references must exist.
- Task dependencies and task-to-request links must resolve.
- Every evidence gap has exactly one evidence-result and one traceability row.
- Direct and downstream requirement/decision lists are distinct, duplicate-free, and non-overlapping. Their IDs must exist in Operational Planning v2.
- Direct requirement relationships must be supported by a directly linked decision and the planning requirement must reference the evidence gap. Downstream dependencies cannot silently count as direct support.
- Trace request and acquisition-task links are derived from the source records, while requirement and decision links must exactly match the gap's direct/downstream fields.
- All package IDs are unique in their defined scope. Event replay must produce the materialized current state.

## Current state and preserved evidence boundaries

No lifecycle completion has been fabricated. The package has 13 prepared requests, all 13 remain unsent, there are no received responses or completed reviews, zero accepted evidence items, and all 13 planning decisions remain open. The 13 evidence gaps remain open. The package retains the existing eight M5 model families, eight null threshold values, `INSUFFICIENT_EVIDENCE` candidate assessments, and the M6 finding that no qualifying independent confirmation cohort is established. The previously examined test split is not a fresh blind confirmation cohort. Offline inference does not establish service readiness, and a repository inventory does not prove that all organizational records have been found. Evidence acceptance and decision resolution remain separate.

No dataset content or test split was accessed; no stakeholder contact, evidence acquisition, model training/inference/scoring, metric or threshold calculation, MLflow change, deployment, staging, commit, or push occurred.

## Validation performed

Focused v3 tests were run first:

```text
PYTHONDONTWRITEBYTECODE=1 python3 -m unittest discover -s tests -p 'test_evidence_lifecycle.py' -v
Ran 21 tests — OK
```

The tests use isolated synthetic records and the current v3/Planning v2 package. They cover successful and invalid request transitions, authorization and dispatch prerequisites, required attribution/provenance, response supersession and cycles, review/acceptance prerequisites, rejected-review disposition, material-correction invalidation, authorized resolution, event uniqueness/order/replay, duplicate legacy status rejection, direct-link mismatch rejection, and current package status preservation.

The existing v2 tests were run after a narrow test correction required by the README update:

```text
PYTHONDONTWRITEBYTECODE=1 python3 -m unittest discover -s tests -p 'test_evidence_acquisition_v2.py' -v
Ran 8 tests — OK
```

That test now treats the README digest recorded by v2 as a historical snapshot instead of requiring today's README to keep the old digest. All other v2 source-inventory hashes continue to be checked against the live files. Additional checks: Python compilation passed for the lifecycle module and both focused test modules; JSON parsing, package-to-Planning-v2 lifecycle/traceability validation, Markdown consistency spot checks, and `git diff --check` passed.

Historical artifact SHA-256 checks matched the baseline (all preserved unchanged):

| Artifact | SHA-256 |
|---|---|
| Evidence Acquisition v1 JSON | `cb48aebd9e00ac5479396ea36021c36358fd820035f4a17a30eda874aeea3b84` |
| Evidence Acquisition v1 Markdown | `ec4d997a1797b3b689f045c440262e040356e7dec57a12a482ef81cb70e54dba` |
| Evidence Acquisition v2 JSON | `0417f1c173ffdb1f46936ce6ebc06bbc3f566a6560f76ba8ebde35c54ea639de` |
| Evidence Acquisition v2 Markdown | `110d2b87c454745b6976f67f98343ba54e2920cb6b41cba50167466e4443260a` |
| Operational Planning v2 JSON | `8c3ebe1df068fd23d34f922db13e6b660958311994cac3809c108caf27b31f1c` |
| Operational Planning v2 Markdown | `3c215ce9eae21fc8a7f5c21c17a3440cdf61e79b50fe55e3150d341d2766ce0a` |
| M5 policy v2 | `a0d1fb0431c2888b4ac48cd862c526ee8fe0ef81370cc77d96141fe6f7a9f54d` |
| M5 analysis | `2a31a7ac022cf82d2296993106eee57e0e326d6633fca9f7ce789ac0b214203b` |
| M6 evidence-readiness report | `ebe13a58d27ace0d3bad930fa02149687f5584fcb9b552fb50fbf0e0bc5ebf83` |

The pre-task staged name/status list matches the final staged list exactly; no v3 files were staged. Existing staged, unstaged, and untracked work was retained. The only edits to already-dirty material were the requested README reference update and the narrowly scoped v2 test adjustment described above.

## Governance limitations and verdict

The module checks that an authorization record states `AUTHORIZED` or `DENIED` and contains attribution; it cannot verify that an organizational actor truly holds that authority because no role assignment, identity provider, signature scheme, or approval service is present. The APIs return new values but do not provide transactional persistence or protect previous JSON files from manual edits. Material response correction and evidence-result acceptance are separate records, so a caller must invalidate affected prior acceptance records and re-review before the package validator will pass.

**Verdict: `READY_WITH_GAPS`.** The v3 package and validator provide controlled application-level transition and traceability validation for the current scope. The verdict does not authorize outreach, establish that roles are formally authorized, mean evidence was acquired or accepted, resolve a planning decision, approve independent evaluation, or authorize production.
