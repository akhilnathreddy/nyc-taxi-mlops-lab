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

I chose separate blocking and warning checks because not every data issue has the same impact. Critical integrity failures, such as missing required fields, unknown zones or incorrect months, should stop the pipeline. Unusual values should generate warnings without stopping ingestion. This protects data quality while keeping the pipeline operational.

## What would show this was wrong

- A real month is blocked by `pickups_in_month`, `required_fields` or `zones_in_lookup` on a handful of rows that turn out to be legitimate. Then those thresholds need headroom, like the month check has.
- `passenger_count_nulls` fires on real months as the trend continues past 15%. Then a month-over-month jump check fits better than a level.
- A corrupt month passes every blocking check and reaches the mart. That shows which integrity check is missing.
- The volume floor blocks a real month (a holiday month, a strike), or lets a partly truncated file through because it is still above 50%.
