# Validation Operating-Point Reconciliation

## Scope and sources

This reconciliation uses the saved common-cohort precision-recall coordinates and the latest operational-feasibility JSON/Markdown. No model was loaded, no prediction or scoring function was executed, and the saved score-table contents were not read. The score-table path and hash were checked against its analysis manifest; the existing curve coordinates are the source of the operating-point counts below.

Sources inspected:

- `reports/validation_analysis/1d24658eef4f4241b4f4e4c1e3a00578/d034e61aaf394581ab9ffb8e3c471089/precision_recall_curves.json`
- `reports/validation_analysis/1d24658eef4f4241b4f4e4c1e3a00578/d034e61aaf394581ab9ffb8e3c471089/analysis_manifest.json`
- `reports/validation_analysis/1d24658eef4f4241b4f4e4c1e3a00578/d034e61aaf394581ab9ffb8e3c471089/validation_scores.parquet` (existence/hash only)
- `reports/validation_analysis/operational_feasibility_v1/1d24658eef4f4241b4f4e4c1e3a00578/a3d9952ae0f44206a6b4f1e20c372a5d/operational_feasibility_report.json`
- `reports/validation_analysis/operational_feasibility_v1/1d24658eef4f4241b4f4e4c1e3a00578/a3d9952ae0f44206a6b4f1e20c372a5d/operational_feasibility_report.md`
- The operational-feasibility `analysis_manifest.json`, which records the source hashes.

The saved common cohort has 56 fraud cases. The score-table SHA-256 is `d3af8746d40a687a6bce5f7b6219bf66e91b8a876444ed509d7d168bd367d945`; it matches the analysis manifest and the operational report manifest.

## Earlier audit availability

No separate persisted precision-recall operating-point audit was found in the repository report outputs. The available project conversation refers to an earlier audit, but its numeric results and selection policy are not present in the files available for this reconciliation. Therefore, the specific values that conflict with the latest report cannot be listed or compared, and the cause of that historical discrepancy remains unresolved.

## Verified latest-report coordinates

The latest report uses the nearest stored recall coordinate for each requested target. Its recorded tie policy selects the highest precision among points at that nearest recall, then the higher recall. Coordinate indices below are zero-based indices into the saved common-cohort precision and recall arrays. The curve file does not store threshold values.

Counts are recovered from the saved coordinate and the 56 positives: `TP = round(recall × 56)`, `FN = 56 − TP`, `alerts = round(TP ÷ precision)`, and `FP = alerts − TP`. All values reconcile to the selected curve coordinates within floating-point tolerance.

| Model | Target recall | Coordinate index | Achieved recall | Precision | TP | FN | FP | Alerts |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| Random Forest | 80% | 35 | 0.803571 | 0.849057 | 45 | 11 | 8 | 53 |
| Random Forest | 90% | 6 | 0.892857 | 0.196850 | 50 | 6 | 204 | 254 |
| Random Forest | 95% | 1 | 0.928571 | 0.018505 | 52 | 4 | 2,758 | 2,810 |
| MLP | 80% | 42,391 | 0.803571 | 0.737705 | 45 | 11 | 16 | 61 |
| MLP | 90% | 42,332 | 0.892857 | 0.406504 | 50 | 6 | 73 | 123 |
| MLP | 95% | 37,139 | 0.946429 | 0.009955 | 53 | 3 | 5,271 | 5,324 |

### Count-identity checks

All six points satisfy:

- `alerts = TP + FP`.
- `FN = 56 − TP`.
- `precision = TP / alerts`.
- `recall = TP / 56`.

For example, the Random Forest 90% target point has 254 alerts = 50 TP + 204 FP; FN = 56 − 50 = 6; precision = 50/254 = 0.196850; recall = 50/56 = 0.892857. The corresponding MLP point has 123 alerts = 50 TP + 73 FP; FN = 6; precision = 50/123 = 0.406504; recall = 0.892857.

## Coordinate ties and discrepancy assessment

Several selected achieved-recall values occur at multiple curve coordinates with different precision values: Random Forest has two coordinates at recall 0.892857; MLP has three at 0.803571, 89 at 0.892857, and 2,476 at 0.946429. The latest report explicitly chooses the highest-precision coordinate within those repeated-recall groups. This is a concrete mechanism by which another audit using a different tie-breaking rule could report different precision, false-positive, and alert counts at the same achieved recall.

However, because the earlier audit’s numerical values and policy are not available as a persisted artifact, it cannot be established that tie-breaking caused its discrepancy. The selected coordinates and count arithmetic in the latest report are internally consistent; no rounding or implementation error was found in those values. Differences from an unretrievable earlier report remain unresolved rather than attributed to a guessed cause.

## Remaining limitations

- These are descriptive validation operating points only; no threshold value is stored in the curve artifact or recommended here.
- The 95% targets are approximate: the nearest Random Forest point reaches 92.86% recall, while MLP reaches 94.64%.
- The earlier audit cannot be reconciled numerically without its output or its selection policy.
- The validation cohort was used for model/checkpoint selection, and the test split was examined previously; these counts do not establish future operational outcomes.

No test data or labels were accessed. No training, model loading, inference, scoring, or MLflow modification occurred. Existing reports and artifacts were not modified.
