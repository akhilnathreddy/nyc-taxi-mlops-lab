# 006: Integrity checks block, anomalies warn, thresholds from 2024-01..04

Stage: S1 · Date: 2026-11-21 · Author: akhilnathreddy · Drafted by agent: yes

## Choice

A check blocks (the month never reaches `zone_hour_stats`) when its failure means the data is wrong or incomplete. It warns (the month loads, the check shows as failed) when its failure means the data is unusual but real. Thresholds are the most a month may have, as a share of its rows, set from what January to April 2024 actually contain (measured in Redshift, `staging.stg_trips`).

| Check | Asset | Blocks? | Threshold | Observed 2024-01..04 |
|---|---|---|---|---|
| `schema_contract` | `trip_files` | block (contract) | any difference in column count, order, name (case-insensitive) or Parquet type | all 4 match |
| `row_count_matches_file` | `stg_trips` | block | exact: loaded rows = footer rows | exact in all 4 |
| `required_fields` (null pickup/dropoff time or zone) | `stg_trips` | block | 0 | 0 |
| `zones_in_lookup` | `stg_trips` | block | 0 | 0 |
| `pickups_in_month` | `stg_trips` | block | 0.01% | 9 to 23 rows, max 0.0006% |
| `month_volume` | `stg_trips` | block | rows ≥ 50% of the median of the other loaded months | 2.96M to 3.58M (floor today ≈ 1.5M to 1.76M) |
| `passenger_count_nulls` | `stg_trips` | warn | 15% | 4.7%, 6.2%, 11.9%, 11.6% |
| `nonpositive_duration` | `stg_trips` | warn | 0.1% | max 0.031% |
| `over_3h` | `stg_trips` | warn | 0.2% | max 0.067% |
| `zero_distance` | `stg_trips` | warn | 7.5% | 1.3% to 2.4% |
| `negative_fare` | `stg_trips` | warn | 5% | 1.3% to 1.6% |
| `duplicate_trips` | `stg_trips` | warn | 0.01% | 0 or 1 row |

`schema_contract` is strict: I did not allow type widening (INT32 read as INT64, for example). The contract lists exact Parquet types, and a changed type is exactly what gameday's 2023-style file looks like.

## Rejected alternative

Making every check blocking (or every check a warning) with one generous threshold for all of them.

## Why

- A blocking check has to be one I'd stop the pipeline for. Lost rows, missing pickup times or zones, zone ids that don't exist, a file for the wrong month and a truncated file all mean the mart would be wrong. None of them happened even once in four real months (pickups outside the month: at most 23 rows), so zero, or 0.01% for the month check, costs nothing on real data and catches a shifted COPY or a wrong file, which would fail on nearly every row.
- Anomalies like negative fares (refunds), zero-distance trips and very long trips are part of real taxi data. Blocking on them would stop good months for ordinary noise (zero distance already swings between 1.3% and 2.4%). Warning thresholds at about 3x the observed maximum stay quiet on real months and fire when a rate actually moves.
- Null `passenger_count` is the one rising trend: it more than doubled from January to March. A threshold set from January alone (say 5%) would fire every month from March on, and a warning that always fires stops being read. 15% sits above the worst month with room for the trend. It never blocks: `passenger_count` is not a model input.
- `month_volume` is relative (50% of the median of the other months), not a fixed number of rows, so seasonality and slow drift don't trip it, while a half-empty file still does.
- The cost I accept: a zero threshold stops a month for a single bad row of those kinds, which means a manual look and a rerun. The warnings rely on someone reading them; nothing stops on them.

## What would show this was wrong

- A real month is blocked by `pickups_in_month`, `required_fields` or `zones_in_lookup` on a handful of rows that turn out to be legitimate. Then those thresholds need headroom, like the month check has.
- `passenger_count_nulls` fires on real months as the trend continues past 15%. Then a month-over-month jump check fits better than a level.
- A corrupt month passes every blocking check and reaches the mart. That shows which integrity check is missing.
- The volume floor blocks a real month (a holiday month, a strike), or lets a partly truncated file through because it is still above 50%.
