# 009: Training window: every earlier month trains, the latest month is the holdout

Stage: S2 · Date: 2026-11-21 · Author: akhilnathreddy · Drafted by agent: yes

## Choice

`training_set` takes the months in `staging.trip_features`, holds out the latest one, and trains on every month before it (`WINDOW_MONTHS = None` in `pipelines/src/labpipes/defs/training.py`). With 2024-01..04 loaded: train on 2024-01..03 (about 9.5M trips), evaluate on 2024-04 (about 3.5M). The zone-pair distance lookup (`est_distance_miles`) is computed from the training months only. When 2024-05 lands, the window becomes 2024-01..04 and 2024-05 the holdout.

## Rejected alternative

A rolling window of the last two months (train 2024-02..03, test 2024-04), so the model follows recent behaviour and the training set stays the same size.

## Why

- The holdout is always the month after the window. That is how the model is used: trained on the past, quoting trips it hasn't seen. A random split of the same months would leak each month's conditions (weather, events, roadworks) into both sides and flatter the model.
- There are about 260 zones and tens of thousands of zone pairs. Many pairs are rare; more months give them enough trips for a stable median duration, a stable distance estimate and a model that has seen them at all. With only four months loaded, dropping January and February would throw away about 40% of the data.
- The model sees `pickup_dow` and `pickup_hour`, not the month, so January's winter trips aren't treated as March's; they still pull the averages. That is a cost I accept for now.
- The cost: the window grows by one month each time a file lands, so training time and memory on the platform host grow with it.

## What would show this was wrong

- A retrained model is worse on the newest month than one trained on fewer, more recent months (seasonality or a change in traffic that old months drag back).
- Training on the growing window no longer fits the platform host's memory or the time the run can take.
- The gate keeps failing on one slice (for example airport trips in summer) that the older months don't represent.
