# Evidence Acquisition v6 — EVD-09 Blocker Alignment

**Package:** `reports/evidence_acquisition_v6/20261017_9d18b0dc3417481aa24d179c5afb5307/evidence_acquisition.json`
**Package ID:** `evidence-acquisition-v6-20261017_9d18b0dc3417481aa24d179c5afb5307`
**Schema:** `5.0.0` (unchanged)
**Status:** `READY_WITH_GAPS` (unchanged)
**Supersedes current package:** `reports/evidence_acquisition_v5/20261016_878beac23d0848bba190b3f955c1390b/evidence_acquisition.json`
**Operational Planning source:** `reports/operational_planning_v2/20261016_85cd78147e3b41c0ba796f6c1d5d7d19/operational_planning.json`

## Targeted correction

EVD-09 `blocked_by` is now `TASK-03`, `TASK-04`, `TASK-06`, `TASK-14`, matching the existing TASK-07 dependency order in Operational Planning v2. The prior EVD-09 blocker list in v5 was `TASK-03`, `TASK-14`. EVD-09 evidence dependencies remain `EVD-02`, `EVD-03`, `EVD-08`. No task dependencies, evidence relationships, statuses, decisions, authorization fields, or lifecycle events changed.

Operational Planning v2 is preserved unchanged: its TASK-07 dependency list already contains all four blocker tasks, and its EVD-09 record refers to TASK-07 while listing evidence dependencies rather than a `blocked_by` field. This package therefore corrects only the Evidence Acquisition availability inventory and retains Planning v2 as its provenance source.

## Preserved lifecycle state

The successor carries forward the v5 state without lifecycle actions: 13 evidence gaps, 13 prepared unsent requests, 13 pending results, 13 open decisions, and 0 lifecycle events. Authorization remains `UNCONFIGURED`; this correction does not authorize evaluation, data access, threshold calibration, outreach, or production approval.

## Validation

The successor was checked against the existing Planning v2 source with `src.evidence_lifecycle.validate_package`. Checks confirmed the four blocker IDs exist, match TASK-07 dependency order, EVD-09 evidence dependencies resolve, the task dependency graph is acyclic, and existing traceability/lifecycle validation passes. Existing authorization and lifecycle state were preserved.

## Historical artifact hashes

| Artifact | SHA-256 |
|---|---|
| `reports/evidence_acquisition_v1/20261016_c048f5dba2834c66b484dfc6b958880a/evidence_acquisition.json` | `cb48aebd9e00ac5479396ea36021c36358fd820035f4a17a30eda874aeea3b84` |
| `reports/evidence_acquisition_v1/20261016_c048f5dba2834c66b484dfc6b958880a/evidence_acquisition_report.md` | `ec4d997a1797b3b689f045c440262e040356e7dec57a12a482ef81cb70e54dba` |
| `reports/evidence_acquisition_v2/20261016_d32e5b3157544eb4b9c0e1dca5a045d5/evidence_acquisition.json` | `0417f1c173ffdb1f46936ce6ebc06bbc3f566a6560f76ba8ebde35c54ea639de` |
| `reports/evidence_acquisition_v2/20261016_d32e5b3157544eb4b9c0e1dca5a045d5/evidence_acquisition_report.md` | `110d2b87c454745b6976f67f98343ba54e2920cb6b41cba50167466e4443260a` |
| `reports/evidence_acquisition_v3/20261016_c781f422ed224c2ba323b0ce53d0cc13/evidence_acquisition.json` | `41f8f8456c44c848114327b56ca5a4ce789979277a842405a9be1ede2998178b` |
| `reports/evidence_acquisition_v3/20261016_c781f422ed224c2ba323b0ce53d0cc13/evidence_acquisition_report.md` | `f091e1fd7f16b01a7c15bd1a37bdf7f177435a1f28a319b76fdb8861cf0bbbb8` |
| `reports/evidence_acquisition_v4/20261016_df0ca908a99b4c5eab1becad82d49d2c/evidence_acquisition.json` | `c3fba5bcf105fc87c45e6204a270e941b2d9318d83efd712118ec581c3a07b17` |
| `reports/evidence_acquisition_v4/20261016_df0ca908a99b4c5eab1becad82d49d2c/evidence_acquisition_report.md` | `24d29b1c09814f692506682f01bb172b1173203e0064d7d3de414d0ac1f76525` |
| `reports/evidence_acquisition_v5/20261016_878beac23d0848bba190b3f955c1390b/evidence_acquisition.json` | `3a943ded492fff8a3989df364a78e8b12c071fab4af8ae185f0d3bb619fd858d` |
| `reports/evidence_acquisition_v5/20261016_878beac23d0848bba190b3f955c1390b/evidence_acquisition_report.md` | `8a56ed42fb209deceee0cc9b813b8a7a0b3062c501eaa4fdb6641181bd535d49` |
| `reports/operational_planning_v2/20261016_85cd78147e3b41c0ba796f6c1d5d7d19/operational_planning.json` | `8c3ebe1df068fd23d34f922db13e6b660958311994cac3809c108caf27b31f1c` |
| `reports/operational_planning_v2/20261016_85cd78147e3b41c0ba796f6c1d5d7d19/operational_planning_report.md` | `3c215ce9eae21fc8a7f5c21c17a3440cdf61e79b50fe55e3150d341d2766ce0a` |

No historical versioned artifact was modified. The package records the exact v5 JSON and Markdown hashes in `supersedes.prior_current_version`.
