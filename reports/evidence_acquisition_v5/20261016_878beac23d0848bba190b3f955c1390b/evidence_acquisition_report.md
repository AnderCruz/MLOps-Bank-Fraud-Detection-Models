# Evidence Acquisition v5 — Decision Binding and Event Integrity

**Package:** `reports/evidence_acquisition_v5/20261016_878beac23d0848bba190b3f955c1390b/evidence_acquisition.json`
**Package ID:** `evidence-acquisition-v5-20261016_878beac23d0848bba190b3f955c1390b`
**Schema:** `5.0.0`
**Status:** `READY_WITH_GAPS`
**Validator:** `src/evidence_lifecycle.py`
**Operational Planning v2:** `reports/operational_planning_v2/20261016_85cd78147e3b41c0ba796f6c1d5d7d19/operational_planning.json`

## Preserved current state

The package contains 13 evidence gaps, 13 prepared but unsent requests, 13 pending evidence results, 13 open decisions, and zero lifecycle events. It contains no fabricated responses, completed reviews, accepted evidence, or resolved decisions. The authorization policy remains `UNCONFIGURED`; no real-world authority or stakeholder contact is implied.

## Decision-specific evidence policy

Planning v2 `decision_register.decisions[].related_evidence_gap_ids` is the authoritative decision-to-gap mapping. A resolved decision requires **every and only** listed gap, in the recorded Planning v2 order, to have exactly one current evidence result with a current accepted and sufficient review and current accepted disposition. Partial acceptance is never eligible. Unknown, duplicate, missing, unrelated, or extra gaps are rejected. The mapping is copied into the versioned policy and each decision record, then checked against Planning v2 during package validation and again by the public resolution API. For DEC-OPS-10, the required list is EVD-10, EVD-11, and EVD-13; EVD-01 alone cannot satisfy it.

## Event integrity

Lifecycle record identifiers appear only in `supporting_record_refs`; source citations are separated into `source_references` and must exactly match the associated response, review, or acceptance record. V5 checks the complete ordered typed-reference list, identifier type, owning entity, record/event linkage, source list, current resolution record, and resolution evidence list. Unknown, additional, missing, duplicated, contradictory, or wrong-type references fail validation. For each represented record, event time must be greater than or equal to its record timestamp; equal timestamps are allowed. Existing global chronological replay and record-to-record causal constraints remain active.

## V4 findings corrected

1. Resolution event evidence refs are compared exactly to the current resolution record, with exactly one matching resolution event.
2. Resolution requires all decision-specific Planning v2 evidence gaps to be currently eligible.
3. Event typed references and source citations are validated separately and bound to their exact records.
4. Authorization, dispatch, response, review, acceptance, and resolution event timestamps cannot precede their associated record timestamps.

The dedicated `tests/test_evidence_acquisition_v5.py` exercises valid synthetic controls and one-invariant mutations. The positive all-gaps resolution fixture is synthetic only: it constructs a hypothetical routed association for EVD-10 because the current real package has no request for that blocked gap. The persisted package is unchanged in lifecycle state and does not claim that evidence was acquired.

## Validation and preservation

Targeted lifecycle, v2 regression, v4 regression, and v5 regression suites passed. The package was validated against Operational Planning v2. Historical package and planning hashes were checked unchanged. `git diff --check` passed. No datasets, test split, models, inference, training, MLflow, or external contacts were involved.

## Limitations

The checks enforce application-level consistency only. They do not authenticate actor identity, verify organizational authority, make JSON storage append-only or tamper-proof, establish that any evidence exists, authorize stakeholder outreach, approve independent evaluation, or grant production approval. The package remains `READY_WITH_GAPS`.



## Content hashes verified

| Artifact | SHA-256 |
|---|---|
| `reports/evidence_acquisition_v1/20261016_c048f5dba2834c66b484dfc6b958880a/evidence_acquisition.json` | `cb48aebd9e00ac5479396ea36021c36358fd820035f4a17a30eda874aeea3b84` |
| `reports/evidence_acquisition_v2/20261016_d32e5b3157544eb4b9c0e1dca5a045d5/evidence_acquisition.json` | `0417f1c173ffdb1f46936ce6ebc06bbc3f566a6560f76ba8ebde35c54ea639de` |
| `reports/evidence_acquisition_v3/20261016_c781f422ed224c2ba323b0ce53d0cc13/evidence_acquisition.json` | `41f8f8456c44c848114327b56ca5a4ce789979277a842405a9be1ede2998178b` |
| `reports/evidence_acquisition_v4/20261016_df0ca908a99b4c5eab1becad82d49d2c/evidence_acquisition.json` | `c3fba5bcf105fc87c45e6204a270e941b2d9318d83efd712118ec581c3a07b17` |
| `reports/operational_planning_v2/20261016_85cd78147e3b41c0ba796f6c1d5d7d19/operational_planning.json` | `8c3ebe1df068fd23d34f922db13e6b660958311994cac3809c108caf27b31f1c` |
| `reports/evidence_acquisition_v5/20261016_878beac23d0848bba190b3f955c1390b/evidence_acquisition.json` | `3a943ded492fff8a3989df364a78e8b12c071fab4af8ae185f0d3bb619fd858d` |
| `src/evidence_lifecycle.py` | `5705fe11db9201bdfa6949daa3e85568d09eaaa00792f9657377c4ec96deb275` |
