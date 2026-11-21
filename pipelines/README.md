# pipelines/

Dagster 1.13.25 (pinned in `pyproject.toml`). One code location, `labpipes.definitions`, which loads every module in `src/labpipes/defs/`.

```
trips/ in the bucket --sensor--> trip_files[month] --(schema_contract, blocking)--> raw_trips[month]
                                                                                       |
                                 stg_trips[month] <------------------------------------+
                                      |--(quality checks)--> zone_hour_stats <-- taxi_zones
```

| Piece | Where | Given or built |
| --- | --- | --- |
| Resources: `RedshiftData` (Data API, `--db-user`, no passwords), `DataBucket` (lists `trips/`, reads Parquet footers) | `src/labpipes/resources.py` | given |
| Partitions `trip_months` (one per landed file), contract readers, SQL loader | `partitions.py`, `contracts.py`, `sql.py` | given |
| `taxi_zones`, `trip_files`, `stg_trips`, `zone_hour_stats` | `defs/zones.py`, `trip_files.py`, `staging.py`, `marts.py` | given |
| `schema_contract` check, `raw_trips`, data-quality checks, sensor and job | `defs/schema_check.py`, `raw_trips.py`, `quality.py`, `sensor.py` | built in S1 |
| One asset, one blocking check, one sensor to copy from | `reference/patterns.py` | given |
| Container entrypoint (RDS secret at start-up, database creation, MLflow server), status for the grader | `runtime.py`, `status.py` | given |
| Models: v1 baseline, v2 LightGBM, the zone-pair distance lookup, evaluation | `src/tripmodel/` | given (S2) |
| `trip_features`; resources `ArtifactBucket`, `MlflowTracking` | `defs/features.py`, `resources.py` | given (S2) |
| `feature_contract` check; `training_set`, `trained_model`, `eval_report`, the `beats_champion` gate, `challenger` | `defs/feature_check.py`, `training.py` | built in S2 |

S6 adds the `wiki_*` assets. Jobs: `ingest_month` (the sensor's, one month to the mart) and `train_model` (window to challenger); start either from the UI or `scripts/dagster-run.sh`.

**Tests:** `make test-pipelines` (fake Redshift and S3, no AWS). **Image:** `docker build -f pipelines/Dockerfile .` from the repo root (it reads `contracts/`). **Runtime:** `deploy/compose.platform.yaml` on the platform host; `dagster.yaml` keeps run storage in the `dagster` database on RDS, runs two at a time, and lets one Redshift-writing step run at a time (pool `redshift`).

**Local UI without AWS resources:** `cd pipelines && uv run dagster dev -m labpipes.definitions` shows the asset graph. Materializing needs Redshift and the bucket, so set `REDSHIFT_CLUSTER_ID=lab REDSHIFT_DATABASE=lab REDSHIFT_DB_USER=labadmin LAB_DATA_BUCKET=<bucket>` with Learner Lab credentials exported.

## S1 as built

**Sensor and job.** `trip_files_sensor` (every 60 s) lists `trips/` and keeps each month's ETag in its cursor. A new month is added to `trip_months` and gets an `ingest_month` run; a replaced file (new ETag) runs again; `run_key = <month>:<etag>`, so the same file never runs twice. `ingest_month` selects everything between `trip_files` and `zone_hour_stats` by graph, with their checks; `taxi_zones` is static and materialized once by hand.

**Load.** `raw_trips` COPYs the month into a temp table shaped exactly like `contracts/trips.schema.yaml` (Parquet COPY maps by position, so it can't fill `source_file`), then deletes and inserts the month in `ingest.raw_trips`, all in one transaction ([decision 004](../decisions/004-copy-vs-spectrum.md)). Table keys follow [decision 005](../decisions/005-dist-and-sort-keys.md).

**Checks.** Blocking checks stop the run before `zone_hour_stats`; warnings show as failed but let the month through. Thresholds are constants at the top of `defs/quality.py`; [decision 006](../decisions/006-blocking-vs-warning.md) has the measured numbers behind each.

| Check | On | Blocks? | Fails when |
| --- | --- | --- | --- |
| `schema_contract` | `trip_files` | yes (contract) | the footer differs from the contract in column count, order, name (case-insensitive) or Parquet type |
| `row_count_matches_file` | `stg_trips` | yes | loaded rows ≠ the file's footer rows |
| `required_fields` | `stg_trips` | yes | any null pickup/dropoff time or zone |
| `zones_in_lookup` | `stg_trips` | yes | any zone id not in `taxi_zones` |
| `pickups_in_month` | `stg_trips` | yes | > 0.01% of pickups fall outside the partition's month |
| `month_volume` | `stg_trips` | yes | rows < 50% of the median of the other loaded months |
| `passenger_count_nulls` | `stg_trips` | warn | > 15% |
| `nonpositive_duration` / `over_3h` | `stg_trips` | warn | > 0.1% / > 0.2% |
| `zero_distance` / `negative_fare` | `stg_trips` | warn | > 7.5% / > 5% |
| `duplicate_trips` | `stg_trips` | warn | > 0.01% exact repeats |

**Tests.** `tests/test_ingest.py`: a contract file is copied; changed types and an appended column block the COPY; a reload replaces the month in one transaction; the sensor runs new and replaced files once; a blocking quality failure keeps the month out of the mart and a warning doesn't.

**Reload a month** (idempotent): `scripts/dagster-run.sh ingest_month --partition 2024-03 --wait`, or Materialize in the UI.
