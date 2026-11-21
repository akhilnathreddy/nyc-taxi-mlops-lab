# 005: Dist and sort keys for the trip tables

Stage: S1 · Date: 2026-11-21 · Author: akhilnathreddy · Drafted by agent: yes

## Choice

| Table | Distribution | Sort key |
|---|---|---|
| `ingest.raw_trips` | `DISTSTYLE AUTO` | `SORTKEY (source_file)` |
| `staging.stg_trips` | `DISTSTYLE AUTO` | `SORTKEY (pickup_at)` |
| `ingest.taxi_zones` | `DISTSTYLE ALL` | none |

## Rejected alternative

`DISTKEY (pickup_zone_id)` on `raw_trips` and `stg_trips`, so that every trip from one zone sits on the same slice and the mart's zone-and-hour aggregation and its join to `taxi_zones` happen without moving rows between slices.

## Why

I chose `SORTKEY(source_file)` for raw_trips to optimize monthly ingestion and `SORTKEY(pickup_at)` for stg_trips to support time-based analytics. I chose `DISTSTYLE AUTO` because the cluster has only two slices, making manual distribution less beneficial. For the small taxi_zones table, I chose `DISTSTYLE ALL` to improve joins.

## What would show this was wrong

- `svv_table_info.skew_rows` for `raw_trips` or `stg_trips` is high, or the query plans for the mart show `DS_BCAST_INNER` / `DS_DIST_BOTH` steps that dominate its run time.
- The cluster grows to 2 nodes (the Learner Lab maximum) and the mart slows down from redistributing rows by zone: then a zone dist key earns its skew.
- Most reads of `stg_trips` filter on zone rather than time (for example the S7 assistant's queries), so a compound sort key on `(pickup_zone_id, pickup_at)` would skip more blocks.
