# 004: Load each month with COPY, not query the files in place with Spectrum

Stage: S1 · Date: 2026-11-21 · Author: akhilnathreddy · Drafted by agent: yes

## Choice

`raw_trips` COPYs each month's Parquet file into `ingest.raw_trips` (`iam_role default`, the cluster's LabRole). Each run COPYs into a temp table shaped exactly like `contracts/trips.schema.yaml`, then deletes the month's rows (by `source_file`) and inserts the new ones, in one transaction. Re-running a month replaces it instead of duplicating it, and a failed COPY leaves the previous load in place.

## Rejected alternative

Redshift Spectrum: an external table over `trips/` in the data bucket (external schema in the Glue catalog), with `stg_trips` reading the files in place.

## Why

I chose COPY because my pipeline repeatedly processes monthly taxi data for analytics and ML. Loading data into Redshift avoids repeated S3 scans and supports safe monthly reruns through transactions. Spectrum avoids data duplication but introduces additional dependencies and changes to the existing staging SQL. COPY is a better fit for my current workload.

## What would show this was wrong

- Months arrive faster or larger than COPY can load them within the run's time budget, or Redshift storage becomes the constraint.
- Most queries turn out to touch each month once (load and forget), so storing it buys nothing over scanning in place.
- I need to query raw files that deliberately should not pass the gate (to investigate a rejected month), which Spectrum would allow without loading them.
