# Evidence Acquisition v4 — Validation Integrity Corrections

**Package:** `reports/evidence_acquisition_v4/20261016_df0ca908a99b4c5eab1becad82d49d2c/evidence_acquisition.json`
**Package ID:** `evidence-acquisition-v4-20261016_df0ca908a99b4c5eab1becad82d49d2c`
**Schema:** `4.0.0`
**Package status:** `READY_WITH_GAPS`
**Validator:** `src/evidence_lifecycle.py`
**Validator SHA-256:** `e755286f1082c73251938057278c601a99517be5964e942bf9ff208f355fa163`
**Operational Planning v2:** `reports/operational_planning_v2/20261016_85cd78147e3b41c0ba796f6c1d5d7d19/operational_planning.json`
**Planning SHA-256:** `8c3ebe1df068fd23d34f922db13e6b660958311994cac3809c108caf27b31f1c`

## Scope and preserved state

V4 supersedes v3 as the current lifecycle package while preserving v1, v2, v3, Operational Planning v2, and M5/M6 artifacts. The package still records **13 open evidence gaps, 13 prepared unsent requests, 13 pending evidence results, 13 open decisions, and zero lifecycle events**. It contains no fabricated responses, completed reviews, accepted evidence, or resolved decisions. Requests remain unsent; this package does not authorize outreach.

The v3 audit returned `NOT_READY` for five material areas: decision resolution could use ineligible evidence; acceptance could diverge from its supporting review; actor attribution was not organizational authorization; event replay lacked complete semantics/references/causal chronology; and duplicate evidence results or dangling task-gap references could pass.

## V4 corrections

1. **Decision evidence eligibility:** `resolve_decision()` and independent package validation require every evidence reference to identify exactly one result and require a current `ACCEPTED` result backed by the current `ACCEPTED` and `SUFFICIENT` review and a valid current acceptance. Pending, rejected, partial, stale, re-review-required, missing, ambiguous, and mixed eligible/ineligible references fail. Partial acceptance is explicitly ineligible for resolution.
2. **Review and acceptance integrity:** Current reviews and acceptances are validated against their declared record fields, current response/review pointers, outcome/sufficiency, attribution, timestamps, rationale, sources, and event IDs. Acceptance must cite the exact current review; supporting sources must be covered by review sources. Material response correction requires review against the current response. Mutating required acceptance fields or its event binding fails.
3. **Authority vs attribution:** The package records `authorization_policy.status=UNCONFIGURED`, with no trusted identity source or allowed roles/identities. V4 APIs require an explicit matching policy for authority-dependent actions. `TEST_ONLY` policies support synthetic tests only. A `CONFIGURED` policy is accepted only with an explicitly verified organizational authority flag and trusted identity source. These checks match claims to configuration; they do not authenticate an actor.
4. **Event contract and chronology:** Replay checks known event types, allowed entity/domain/state transition combinations, entity/state existence, unique IDs, actor policy, typed supporting record references, prior state, chronology, correction/supersession semantics, and replayed/materialized state agreement. Package validation binds current and versioned records to matching events and checks authorization ≤ dispatch ≤ response receipt ≤ review ≤ acceptance ≤ decision resolution where linked. Event timestamps must be globally nondecreasing, and record timestamps must respect causal dependencies.
5. **Structural/traceability integrity:** Collection IDs and evidence result cardinality are checked before lookup maps are used. V4 requires exactly one result per known gap, unique IDs, known task-gap references, reciprocal request/task links in both directions, valid direct/downstream Planning v2 IDs and classifications, and non-orphaned current review/acceptance/response/event/supersession references. V4 also repairs reciprocal request links for ACQ-20 without changing evidence state.

Event history validation is application-level. A coordinated rewrite of records, events, and pointers may not be detectable without signed events, trusted identity, and protected/versioned storage. The implementation does not claim cryptographic immutability, transactional persistence, authenticated organizational identity, or tamper-proofing.

## Validation performed

All tests use synthetic or repository package/plan records; the lifecycle test suite does not train models, load models, score data, calculate model metrics, or access datasets.

```text
PYTHONDONTWRITEBYTECODE=1 python3 -m unittest discover -s tests -p 'test_evidence_lifecycle.py' -v
Ran 21 tests — OK

PYTHONDONTWRITEBYTECODE=1 python3 -m unittest discover -s tests -p 'test_evidence_acquisition_v2.py' -v
Ran 8 tests — OK

PYTHONDONTWRITEBYTECODE=1 python3 -m unittest discover -s tests -p 'test_evidence_acquisition_v4.py' -v
Ran 12 tests — OK
```

The regression cases include positive synthetic acceptance/resolution, pending/rejected/partial/nonexistent/mixed evidence, arbitrary actor claims, incomplete or mutated acceptance/review fields, duplicate result and entity IDs, unknown task-gap IDs, missing reciprocal links, invalid direct/downstream and Planning v2 references, orphaned review/acceptance, malformed supersession, unknown/incompatible events and record references, missing/unauthorized actors, cancellation events without reasons, duplicate/reordered/missing events, current-state replay mismatch, and dispatch-before-authorization chronology. `git diff --check` and independent JSON/package-to-Planning-v2 validation were also run.

## Historical baseline hashes

The v1–v3 package files were not edited. Their live SHA-256 values match recorded baselines:

| Artifact | SHA-256 | Baseline result |
|---|---|---|
| v1 JSON | `cb48aebd9e00ac5479396ea36021c36358fd820035f4a17a30eda874aeea3b84` | Matches recorded v1 baseline |
| v1 Markdown | `ec4d997a1797b3b689f045c440262e040356e7dec57a12a482ef81cb70e54dba` | Matches recorded v1 baseline |
| v2 JSON | `0417f1c173ffdb1f46936ce6ebc06bbc3f566a6560f76ba8ebde35c54ea639de` | Matches recorded v2 baseline |
| v2 Markdown | `110d2b87c454745b6976f67f98343ba54e2920cb6b41cba50167466e4443260a` | Matches recorded v2 baseline |
| v3 JSON | `41f8f8456c44c848114327b56ca5a4ce789979277a842405a9be1ede2998178b` | Matches recorded v3 baseline |
| v3 Markdown | `f091e1fd7f16b01a7c15bd1a37bdf7f177435a1f28a319b76fdb8861cf0bbbb8` | Matches recorded v3 baseline |
| Operational Planning v2 JSON | `8c3ebe1df068fd23d34f922db13e6b660958311994cac3809c108caf27b31f1c` | Matches package source reference |
| Operational Planning v2 Markdown | `3c215ce9eae21fc8a7f5c21c17a3440cdf61e79b50fe55e3150d341d2766ce0a` | Matches package source reference |
| M5 policy v2 | `a0d1fb0431c2888b4ac48cd862c526ee8fe0ef81370cc77d96141fe6f7a9f54d` | Matches package source reference |
| M5 analysis | `2a31a7ac022cf82d2296993106eee57e0e326d6633fca9f7ce789ac0b214203b` | Matches package source reference |
| M6 report | `ebe13a58d27ace0d3bad930fa02149687f5584fcb9b552fb50fbf0e0bc5ebf83` | Matches package source reference |

V4 JSON SHA-256: `c3fba5bcf105fc87c45e6204a270e941b2d9318d83efd712118ec581c3a07b17`.

## Verdict and limits

**Verdict: `READY_WITH_GAPS`.** The application-level controls now reject the identified ineligible-resolution, invalid-acceptance, replay/reference/chronology, and traceability bypasses, with positive and negative regression coverage. External organizational authorization remains unconfigured, and storage is mutable and not tamper-proof. Before real lifecycle actions, configure and independently verify the identity/authority source and approved scope mapping, and use protected/versioned persistence. V4 neither evidences acquisition nor authorizes stakeholder contact, independent model evaluation, threshold acceptance, or production approval.

No stakeholder requests were sent. All decisions remain open. No model training, inference, scoring, dataset/test-split access, or MLflow write occurred. No files were staged, committed, or pushed.
