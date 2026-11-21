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
