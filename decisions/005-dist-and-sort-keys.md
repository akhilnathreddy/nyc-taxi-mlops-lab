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

- The cluster is one `ra3.large` node with 2 slices. Distribution decides which slice a row lives on; with 2 slices on one node there is almost no network redistribution to save, so a hand-picked dist key buys little. `AUTO` lets Redshift choose (and change) the style as the tables grow, which is the right default at this size.
- A key on `pickup_zone_id` would also skew: a few zones (Midtown, the airports, the Upper East Side) carry a large share of trips, so one slice would do more of the work. `AUTO` doesn't have that risk.
- Sort keys are what matter here. Zone maps let Redshift skip whole blocks whose min/max fall outside a filter.
  - Every statement on `raw_trips` filters on one month's `source_file`: the reload's `delete`, the row count, and `stg_trips`' `select ... where source_file = '{file}'`. Sorting on it means each of those reads only that month's blocks.
  - `stg_trips` is read by time: per-month checks, the mart, and S2's training windows all filter or group on pickup time, so `pickup_at` keeps those range scans narrow.
- `taxi_zones` is about 265 rows. `DISTSTYLE ALL` puts a full copy on every slice, so joining it to trips never moves the trip rows. The copy costs nothing at this size.

## What would show this was wrong

- `svv_table_info.skew_rows` for `raw_trips` or `stg_trips` is high, or the query plans for the mart show `DS_BCAST_INNER` / `DS_DIST_BOTH` steps that dominate its run time.
- The cluster grows to 2 nodes (the Learner Lab maximum) and the mart slows down from redistributing rows by zone: then a zone dist key earns its skew.
- Most reads of `stg_trips` filter on zone rather than time (for example the S7 assistant's queries), so a compound sort key on `(pickup_zone_id, pickup_at)` would skip more blocks.
