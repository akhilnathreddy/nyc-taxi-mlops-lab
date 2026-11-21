# 008: Promotion: MAE at least 2% better, no slice more than 5% worse, p95 within 25 ms

Stage: S2 · Date: 2026-11-21 · Author: akhilnathreddy · Drafted by agent: yes

## Choice

A newly trained version becomes `challenger` only if, on the same holdout month as the incumbent (the `champion`, or the v1 baseline trained on the same window before there is one), all three hold. The blocking `beats_champion` check on `eval_report` enforces them, and `challenger` re-checks them before it sets the alias:

| Rule | Constant in `defs/training.py` | Value |
| --- | --- | --- |
| Overall holdout MAE at least this much lower than the incumbent's | `MIN_MAE_GAIN` | 2% |
| No slice (airport, manhattan, outer, night) more than this much worse | `MAX_SLICE_LOSS` | 5% |
| Single-row p95 latency, in process | `P95_LATENCY_BUDGET_MS` | 25 ms |

First run (version 1, trained on 2024-01..03, holdout 2024-04, 3.48M trips) against the v1 baseline:

| | v2 (version 1) | v1 baseline | |
| --- | --- | --- | --- |
| MAE overall | 3.638 min | 3.956 min | 8.1% better (needed 2%) |
| airport | 5.98 | 6.72 | 11.1% better |
| manhattan | 3.15 | 3.34 | 5.6% better |
| outer | 7.42 | 9.19 | 19.3% better |
| night | 2.61 | 2.87 | 9.0% better |
| p95 latency | 3.2 to 3.6 ms | 0.8 to 0.9 ms | budget 25 ms |

## Rejected alternative

Any improvement in overall MAE, with no slice rule: the simplest gate, and every better model gets through.

## Why

- Both models are scored on the same 3.5M-trip holdout, so even small differences are real for that month. What a margin protects against is churn and over-fitting to one month: every new challenger starts S3's promotion (approval, canary), and a gain of a few seconds per trip is not worth that, nor guaranteed to hold on the next month. 2% of a 3.6-minute MAE is about 4 seconds per trip.
- Overall MAE is dominated by short Manhattan trips. A model can improve the average while getting worse on airport trips, which are long and where a bad quote costs the most. The slice rule stops a version that buys its average at a slice's expense; 5% leaves room for month-to-month noise in the smaller slices.
- The latency budget is the model's share of `/predict`, which adds HTTP, Traefik and JSON on top. v2 measures about 3.5 ms; 25 ms leaves room for a larger model while still catching a roughly 7x regression. The p95 comes from 200 single-row calls and varied between 3.2 and 3.6 ms across two runs, so a budget close to the measurement would fail the same model on a slow run.
- The cost I accept: a real improvement smaller than 2% waits for a later month, and a model that is much better overall but worse on one slice is rejected.

## What would show this was wrong

- Monthly retrains keep landing between 0% and 2% better and never promote, while each is genuinely better on the next month too.
- A promoted version turns out worse in production on a slice the gate doesn't measure (a borough, rush hour, long trips).
- S5's `/predict` latency SLO is breached while the model is within 25 ms: then the model's share is too large and the budget should come down.
