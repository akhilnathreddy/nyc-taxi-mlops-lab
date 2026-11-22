# decisions/

One record per decision point, from [000-template.md](000-template.md): the choice, the alternative I rejected (and will defend), why, and what would show it was wrong.

| # | Stage | Decision | Choice |
| --- | --- | --- | --- |
| [001](001-runner-credentials.md) | S0 | Runner credentials | Instance profile (`LabRole`); no AWS keys in GitHub |
| [002](002-image-tag-scheme.md) | S0 | Image tag scheme | `sha-<short sha>`, never reused; rollback redeploys an earlier tag |
| [003](003-ingress-scope.md) | S0 | Ingress scope | Port 80 from `0.0.0.0/0` only |
| [004](004-copy-vs-spectrum.md) | S1 | COPY vs Spectrum | COPY each month, idempotent per month |
| [005](005-dist-and-sort-keys.md) | S1 | Dist and sort keys | AUTO distribution; sort by `source_file` (raw) and `pickup_at` (staging); `taxi_zones` ALL |
| [006](006-blocking-vs-warning.md) | S1 | Blocking vs warning | Integrity blocks, anomalies warn, thresholds from 2024-01..04 |
| [007](007-notebook-vs-pipeline.md) | S2 | What stays in the notebook | Notebook explores and experiments on samples; pipeline trains, judges, registers, and records each month's duration percentiles and static-quote MAE |
| [008](008-promotion-metric-and-margin.md) | S2 | Promotion metric and margin | MAE ≥ 2% better than the incumbent, no slice > 5% worse, p95 ≤ 25 ms |
| [009](009-training-window.md) | S2 | Training window | Latest month is the holdout; every earlier month trains |
| [010](010-load-vs-reload.md) | S3 | Load at start-up or reload on alias change | Reload in place, called by the approval-gated `promote.yaml`; any pipeline-evaluated version can be promoted |
| [011](011-blue-green-switch-trigger.md) | S3 | What triggers the blue-green switch | Automatic, after the Docker health check, `/healthz` through Traefik and the smoke test pass |
| 012 | S4 | What to automate in a restore | *to write* |
| [013](013-slo-targets.md) | S5 | SLO targets | 99% each: /predict without 5xx, under 250 ms, from a model (not the fallback); multi-window burn-rate pages |
| [014](014-series-budget.md) | S5 | Series budget | Lean keep list per source, no per-deploy labels; under 2,000 active series (426 after 3 deploys) |
| [015](015-chunking-and-top-k.md) | S6 | Chunk size, overlap and top-k | 256 tokens, no overlap (one chunk per page today), top-k 3 |
| [016](016-hnsw-or-ivfflat.md) | S6 | HNSW or IVFFlat | IVFFlat, 1 list (exact at 16 chunks), built after embedding |
