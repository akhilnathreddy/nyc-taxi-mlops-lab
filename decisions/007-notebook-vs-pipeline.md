# 007: The notebook explores and experiments; the pipeline trains, judges, registers and watches each month

Stage: S2 · Date: 2026-11-21 · Author: akhilnathreddy · Drafted by agent: yes

## Choice

The notebook is where I look at the data and try ideas. The pipeline is what makes a model, and what looks at every new month without me. Anything I would otherwise have to remember to rerun by hand moves into the pipeline.

| Step in `notebooks/explore.ipynb` | Where it lives |
| --- | --- |
| Duration distribution, medians by day and hour, zone stats (cells 5–7) | Notebook, to explore. The monthly view of the same shape moves into the pipeline (below) |
| Trying hyperparameters and model ideas on samples (cells 9–10) | Notebook, logged to `trip-duration-notebook` only. A winner reaches the pipeline as a reviewed commit to `LightGBMModel.DEFAULT_PARAMS` (or `tripmodel`), never as a model file |
| Building the training set, fitting v2, logging and registering it with its tags | Pipeline only (`training_set`, `trained_model`) |
| Comparing against the champion or the v1 baseline on the holdout, the gate, the `challenger` alias | Pipeline only (`eval_report`, `beats_champion`, `challenger`; record 008) |
| The zone-pair distance lookup query | One definition, used by both `training_set` and the notebook, so notebook numbers are computed the way the pipeline computes them |
| **Monthly checks moved from exploration** | Pipeline, on each new `trip_features` month: the month's duration percentiles (p10, p50, p90, p99), and the MAE of the static 12.25-minute quote on the holdout, logged next to the contract metrics on the training run. Neither blocks; they are for reading |

A notebook result is a lead, not evidence: only the pipeline's full-data evaluation decides whether a version becomes `challenger`. The notebook never registers a model and never touches an alias.

## Rejected alternative

B: the same split, but with nothing moved from the notebook into the pipeline. Exploration stays something I rerun when I think of it.

## Why

<!-- Draft from the evidence below: rewrite in your own words, as for 004–006. -->

The notebook trains on a 5% sample of 2024-01..03 and tests on a 2% sample of 2024-04, drawn with `random()` and no seed, so its numbers change every run and are a fraction of what the pipeline uses (about 9.5M training trips, about 3.5M holdout trips; record 009). That is fine for ranking ideas quickly, but not for deciding a promotion, so the decision stays in the pipeline.

What made me move the monthly views into the pipeline rather than stop at B is how much the data moves between months. Measured in Redshift (`staging.stg_trips`, the `trip_features` filters):

| | 2024-01 | 2024-02 | 2024-03 | 2024-04 |
| --- | --- | --- | --- | --- |
| Median duration (min) | 11.63 | 12.00 | 12.47 | 12.80 |

| Holdout | Static 12.25 quote, MAE | v1 baseline, MAE |
| --- | --- | --- |
| 2024-03 (trained on 01..02) | 8.45 | 3.90 |
| 2024-04 (trained on 01..03) | 8.61 | 3.96 |

The median trip got about 10% longer in four months, and the app's static quote drifted with it. Under B, that only shows up if someone reopens the notebook. A per-month record in the pipeline shows it every time a month lands, next to the model's own numbers.

The distance lookup is the one piece of logic both sides compute. Two copies of it would let the notebook evaluate on different inputs from what the pipeline trains and serving fills in. That is the same mismatch between notebook and serving that the end-of-S2 colleague change tests.

## What would show this was wrong

- Notebook winners regularly fail to reproduce in the pipeline (a setting that beat v2 on the sample loses on full data). Then the notebook should use a fixed seed, or bigger samples, before anything is committed.
- The monthly percentiles and static-quote MAE are never read, or only repeat what `drift_report` (S8) already says. Then they are noise and should go.
- A real shift in the data is found by hand in the notebook rather than by the pipeline. Then the monthly checks are watching the wrong thing.
- The notebook and `training_set` get different distance lookups for the same window. Then the single definition isn't actually shared.
