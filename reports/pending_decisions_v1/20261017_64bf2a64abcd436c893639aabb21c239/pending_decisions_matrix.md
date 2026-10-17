# Pending Decisions Matrix — Independent Evaluation

## Purpose

Record the unresolved decisions affecting label-process evidence, independent-evaluation boundaries, and production approval.

This matrix is a decision-support document. It does not establish organizational approval, authorize data access, or change project readiness.

## Decision Register

| ID          | Topic                                | Decision Required                                                                                                                                                                              | Available Evidence                                                                                                                                                                     | Interim Position                                                                                                                                     | Impact if Unresolved                                                                            |
| ----------- | ------------------------------------ | ---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | -------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | ---------------------------------------------------------------------------------------------------------------------------------------------------- | ----------------------------------------------------------------------------------------------- |
| DEC-PEND-01 | EVD-02 — Label-process evidence      | Determine whether EVD-01 blocks documentary discovery, project-specific label-policy approval, or both.                                                                                        | TASK-03 has no task dependencies and can start now. EVD-02 depends on EVD-01, but the intended scope of that dependency is not explicitly defined.                                     | Preserve existing dependencies. Documentary discovery may be considered separately from policy approval, subject to applicable access authorization. | Label-policy approval and evaluation-protocol freeze remain blocked by unresolved requirements. |
| DEC-PEND-02 | EVD-02 — Observation window          | Confirm whether observation-window definition and supporting evidence must be explicitly included in EVD-02.                                                                                   | The existing evidence-readiness records identify the observation window as unresolved, but EVD-02's evidence scope does not explicitly enumerate it.                                   | Do not assume the requirement has been approved or satisfied.                                                                                        | Label maturity and cohort qualification criteria cannot be finalized.                           |
| DEC-PEND-03 | EVD-10 — Evidence-package boundary   | Decide whether EVD-10 represents independent-evaluation results only or a combined package spanning evaluation and production readiness.                                                       | TASK-08 covers independent evaluation. TASK-11 covers production approval. TASK-15 covers service benchmarking. EVD-10 currently combines evaluation, benchmark, and decision outputs. | Preserve the existing artifact and dependencies until the intended boundary is approved.                                                             | The completion criteria for EVD-10 remain ambiguous.                                            |
| DEC-PEND-04 | EVD-05, EVD-06, EVD-07 — Stage gates | Determine whether service benchmarks, monitoring requirements, and security/privacy evidence block TASK-08, closure of a combined EVD-10 package, or only production approval through TASK-11. | The task graph separates TASK-08 from the additional operational prerequisites of TASK-11. The semantics of the combined evidence package are not explicit.                            | Retain the existing task dependencies and access restrictions. Do not infer that production readiness is established by model metrics.               | Evaluation completion and production approval criteria cannot be fully reconciled.              |
| DEC-PEND-05 | Acceptance disposition               | Identify the authoritative record for accepting, deferring, or rejecting independent-evaluation results and distinguish it from the final production decision.                                 | TASK-08 and TASK-11 represent distinct stages, but the relationship between their decision records requires clarification.                                                             | Keep evaluation disposition and production approval conceptually separate.                                                                           | Decision authority, reporting, and closure criteria remain incomplete.                          |

## Decision Ownership

The responsible decision-maker or organizational authority for each item has not been established by the reviewed repository evidence.

No owner, approver, or deadline should be inferred from the existing task assignments.

## Dependencies and Restrictions

Until the relevant decisions and evidence are documented:

* Do not remove existing evidence dependencies.
* Do not change lifecycle or authorization states.
* Do not send stakeholder requests without the required authorization.
* Do not access restricted evaluation data.
* Do not use the previously examined test split as fresh independent confirmation.
* Do not execute independent evaluation or threshold calibration.
* Do not approve production readiness based on validation metrics alone.

## Completion Criteria

This decision register can be considered resolved only when:

1. Each question has an explicit, documented answer from an authorized decision-maker.
2. Any resulting policy or dependency changes are reflected in the appropriate versioned artifacts.
3. The changes preserve historical versions and provenance.
4. Relevant lifecycle and dependency validations pass.
5. Unresolved external evidence requirements remain explicitly open.

Until then, EVD-02 and EVD-10 remain unresolved, and the project retains its existing `READY_WITH_GAPS` planning status.
