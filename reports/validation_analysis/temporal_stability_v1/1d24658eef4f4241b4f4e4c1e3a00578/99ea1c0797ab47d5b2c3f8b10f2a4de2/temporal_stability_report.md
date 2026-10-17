# Four-Segment Temporal Stability Analysis

- Evaluation ID: `1d24658eef4f4241b4f4e4c1e3a00578`
- Source curve-analysis ID: `d034e61aaf394581ab9ffb8e3c471089`
- Common cohort: 42,712 observations, 56 frauds, 42,656 legitimate transactions
- This analysis uses only saved validation scores and labels; no model was loaded and no inference was run.
- Scores are continuous. No threshold was selected.

## Segment composition

| Segment | Observation IDs | Rows | Fraud | Legitimate | Fraud prevalence | Share of cohort frauds |
|---|---:|---:|---:|---:|---:|---:|
| 1 | 199373–210050 | 10,678 | 10 | 10,668 | 0.093650% | 17.86% |
| 2 | 210051–220728 | 10,678 | 13 | 10,665 | 0.121746% | 23.21% |
| 3 | 220729–231406 | 10,678 | 14 | 10,664 | 0.131111% | 25.00% |
| 4 | 231407–242084 | 10,678 | 19 | 10,659 | 0.177936% | 33.93% |

## AP by segment

| Model | Segment 1 | Segment 2 | Segment 3 | Segment 4 | Min | Max | Range |
|---|---:|---:|---:|---:|---:|---:|---:|
| random_forest | 0.900094 | 0.748056 | 0.920466 | 0.887771 | 0.748056 | 0.920466 | 0.172410 |
| xgboost | 0.900291 | 0.711839 | 0.837454 | 0.912810 | 0.711839 | 0.912810 | 0.200971 |
| logistic_regression | 0.753472 | 0.593781 | 0.839910 | 0.920394 | 0.593781 | 0.920394 | 0.326613 |
| lightgbm | 0.800739 | 0.662064 | 0.813940 | 0.532204 | 0.532204 | 0.813940 | 0.281736 |
| mlp | 0.900668 | 0.723158 | 0.909273 | 0.914921 | 0.723158 | 0.914921 | 0.191762 |
| autoencoder | 0.242875 | 0.241418 | 0.330171 | 0.492532 | 0.241418 | 0.492532 | 0.251114 |
| lstm | 0.900359 | 0.714011 | 0.881297 | 0.916834 | 0.714011 | 0.916834 | 0.202823 |
| gru | 0.882232 | 0.739964 | 0.892153 | 0.905525 | 0.739964 | 0.905525 | 0.165561 |

## ROC-AUC by segment

| Model | Segment 1 | Segment 2 | Segment 3 | Segment 4 | Min | Max | Range |
|---|---:|---:|---:|---:|---:|---:|---:|
| random_forest | 0.946822 | 0.917343 | 0.996731 | 0.971702 | 0.917343 | 0.996731 | 0.079388 |
| xgboost | 0.967913 | 0.943857 | 0.989189 | 0.997748 | 0.943857 | 0.997748 | 0.053892 |
| logistic_regression | 0.982733 | 0.945140 | 0.984534 | 0.999674 | 0.945140 | 0.999674 | 0.054534 |
| lightgbm | 0.887073 | 0.970962 | 0.915644 | 0.777998 | 0.777998 | 0.970962 | 0.192963 |
| mlp | 0.986061 | 0.947153 | 0.987729 | 0.999585 | 0.947153 | 0.999585 | 0.052432 |
| autoencoder | 0.953093 | 0.923712 | 0.979477 | 0.996805 | 0.923712 | 0.996805 | 0.073094 |
| lstm | 0.974016 | 0.941159 | 0.992920 | 0.998958 | 0.941159 | 0.998958 | 0.057799 |
| gru | 0.977400 | 0.942796 | 0.984239 | 0.998099 | 0.942796 | 0.998099 | 0.055303 |

## Aggregate common-cohort metrics and AP ranks

| Model | AP | ROC-AUC | Aggregate AP rank | Segment AP ranks (1–4) | Segment AP range | Segment ROC-AUC range |
|---|---:|---:|---:|---|---:|---:|
| random_forest | 0.857966387539 | 0.960911335535 | 1 | [4, 1, 1, 6] | 0.748056–0.920466 | 0.917343–0.996731 |
| xgboost | 0.828446705207 | 0.978020593318 | 5 | [3, 5, 6, 4] | 0.711839–0.912810 | 0.943857–0.997748 |
| logistic_regression | 0.784909836970 | 0.980048444031 | 6 | [7, 7, 5, 1] | 0.593781–0.920394 | 0.945140–0.999674 |
| lightgbm | 0.681359403600 | 0.876734390071 | 7 | [6, 6, 7, 7] | 0.532204–0.813940 | 0.777998–0.970962 |
| mlp | 0.855181432048 | 0.982750709999 | 2 | [1, 3, 2, 3] | 0.723158–0.914921 | 0.947153–0.999585 |
| autoencoder | 0.292605519322 | 0.967572808381 | 8 | [8, 8, 8, 8] | 0.241418–0.492532 | 0.923712–0.996805 |
| lstm | 0.853891855719 | 0.979812754528 | 3 | [2, 4, 4, 2] | 0.714011–0.916834 | 0.941159–0.998958 |
| gru | 0.852554652596 | 0.978331636481 | 4 | [5, 2, 3, 5] | 0.739964–0.905525 | 0.942796–0.998099 |

## Interpretation and limitations

The segment metrics are descriptive summaries of four contiguous portions of the common validation cohort. They do not establish statistical significance, model superiority, or concept drift. There are only 56 frauds across the full cohort, so segment metrics are sensitive to a small number of positives. AP and ROC-AUC can rank models differently because they summarize different aspects of ranking performance. The Autoencoder produces a reconstruction-error anomaly score, not a calibrated fraud probability. LSTM and GRU sequences use global chronological transaction order; without entity identifiers they cannot be interpreted as customer histories.

This evaluation reads validation data only. The test split was used in prior analysis and is not an untouched or blind holdout.

No production winner or operating threshold is selected.
