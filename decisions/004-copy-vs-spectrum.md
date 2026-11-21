# 004: Load each month with COPY, not query the files in place with Spectrum

Stage: S1 · Date: 2026-11-21 · Author: akhilnathreddy · Drafted by agent: yes

## Choice

`raw_trips` COPYs each month's Parquet file into `ingest.raw_trips` (`iam_role default`, the cluster's LabRole). Each run COPYs into a temp table shaped exactly like `contracts/trips.schema.yaml`, then deletes the month's rows (by `source_file`) and inserts the new ones, in one transaction. Re-running a month replaces it instead of duplicating it, and a failed COPY leaves the previous load in place.

## Rejected alternative

Redshift Spectrum: an external table over `trips/` in the data bucket (external schema in the Glue catalog), with `stg_trips` reading the files in place.

## Why

- Only what passed the gate is queryable. With COPY, a file enters the warehouse only after `schema_contract` passes and `raw_trips` runs. With Spectrum, a file that lands in the bucket is part of the external table immediately, so a bad month is visible to every query before any check has run.
- Every downstream step (`stg_trips`, the data-quality checks, `zone_hour_stats`, and S2's features) reads the same data several times. With COPY, the S3 read happens once per month. With Spectrum, every query rescans S3 and is billed per byte scanned, and it is slower than reading local, sorted, compressed blocks.
- Dist and sort keys only apply to tables Redshift stores, so COPY is what makes the dist and sort key decision mean anything.
- The given `stg_trips.sql` reads `ingest.raw_trips ... where source_file = '{file}'`. COPY fills `source_file` directly; Spectrum would need a view deriving it from the `"$path"` pseudo-column.
- The cost I accept: the data is stored twice (S3 and Redshift), loading takes time per month, and making the load safe to re-run is my job (the delete-and-insert transaction) rather than something that comes for free.

## What would show this was wrong

- Months arrive faster or larger than COPY can load them within the run's time budget, or Redshift storage becomes the constraint.
- Most queries turn out to touch each month once (load and forget), so storing it buys nothing over scanning in place.
- I need to query raw files that deliberately should not pass the gate (to investigate a rejected month), which Spectrum would allow without loading them.
