# 013: SLO targets: three 99% SLOs on /predict (availability, latency under 250 ms, model coverage)

Stage: S5 · Date: 2026-11-22 · Author: akhilnathreddy · Drafted by agent: yes

## Choice

| SLO | SLI (contracts/metrics.yaml) | Objective |
| --- | --- | --- |
| predict-availability | `/predict` answers that weren't 5xx (`lab_http_requests_total`) | 99% |
| predict-latency | `/predict` answered within 250 ms inside the app (`lab_http_request_duration_seconds`, the `le="0.25"` bucket) | 99% |
| model-coverage | quotes from a model, not the static-median fallback (`lab_predictions_total`, `source`) | 99% |

`observability/slo.yaml` says what each measures and why; `observability/rules/slo.rules.yaml` records each SLI's bad ratio over 5m, 30m, 1h and 6h and pages on multi-window burn rates: 14.4x the budget over 1h *and* 5m (`for: 2m`), or 6x over 6h *and* 30m (`for: 5m`). The burn-rate factors and windows are the Google SRE workbook's defaults for a 30-day budget; I kept them rather than tune them on one day of lab traffic.

## Rejected alternative

99.9% availability. On one app host with no redundancy it allows about 43 minutes of failure a month, and one bad deploy, a Traefik config change (S3's first deploy had a 15-second gap) or a session end would spend it. The alerts would fire for things I've already accepted as part of how the lab runs.

## Why

<!-- Draft from the evidence below: rewrite in your own words, as for 004–006. -->

Availability and latency are what a health check can mostly see; model coverage is the one it can't. A fallback quote is an HTTP 200 with a much worse number (static-quote MAE 8.61 min against 3.96 for v1 on the 2024-04 holdout, record 007), so without that SLO, a dead `serving-champion` would look healthy on every other panel. The promtool tests show it: 20 minutes of fallback-only quotes pages `ModelCoverageFastBurn` and doesn't touch `PredictAvailabilityFastBurn`.

250 ms is far above what the model costs (version 1's p95 is 3.2 ms, and the S2 gate allows 25 ms), so a latency page means the path to serving (Traefik, the timeout, the host) is the problem, not the model. It's a bucket boundary in the contract, so the SLI is exact.

Two windows per alert so a short spike doesn't page and a real outage does (`observability/rules/slo.rules.test.yaml`): 3 minutes of 5xx after an hour of healthy traffic leaves the 1h ratio at 5%, under the 14.4% line, and nothing fires; 20 minutes of 5xx pages within about 10 minutes. The cost of that choice: a fast burn needs about 9 minutes of total failure before it fires, and a partial failure (25% slow) about 35 minutes.

Evidence from the real alert (S5 step 5): `<break time, alert time, fix time>`.

## What would show this was wrong

- A rider-visible problem that none of the three alerts caught, or one they caught only after riders had complained.
- Alerts firing for things nobody would act on (a deploy, a session end): the objective is tighter than how the lab runs.
- No traffic means no ratio: with nobody calling `/predict`, these SLOs are silent. If that hides an outage, an absence alert on `up{job="app"}` is the next thing to add.
- Requests that never reach the app (Traefik with no healthy colour returns its own 5xx) aren't in the availability SLI. If that happens, measure at Traefik's `app-live@file` service instead.
