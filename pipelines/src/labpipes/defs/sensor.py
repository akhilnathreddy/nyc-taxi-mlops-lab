"""S1: the S3 sensor (and the job it starts).

Watch trips/ in the data bucket (DataBucket.trip_files). When a month's file appears or changes, add
the month to the trip_months partitions and request a run that goes from trip_files to zone_hour_stats.
Patterns: pipelines/reference/patterns.py.
"""

import json

import dagster as dg

from ..partitions import trip_months
from ..resources import DataBucket

# trip_files and everything between it and the mart, with their checks: a month that fails a blocking
# check never reaches zone_hour_stats. Selected by graph, not by name, so S2's trip_features stays out.
ingest_job = dg.define_asset_job(
    "ingest_job",
    selection=dg.AssetSelection.assets("trip_files").downstream() & dg.AssetSelection.assets("zone_hour_stats").upstream(),
)


@dg.sensor(job=ingest_job, minimum_interval_seconds=60)
def trip_files_sensor(context: dg.SensorEvaluationContext, data_bucket: DataBucket):
    # Cursor: month -> ETag of the file last requested. A new ETag means the file was replaced.
    seen: dict[str, str] = json.loads(context.cursor or "{}")
    changed = [f for f in data_bucket.trip_files() if seen.get(f.month) != f.etag]
    if not changed:
        return dg.SkipReason("no new or changed trip files")
    known = set(context.instance.get_dynamic_partitions(trip_months.name))
    new = sorted({f.month for f in changed} - known)
    return dg.SensorResult(
        # run_key includes the ETag: the same file is never run twice, a replaced one runs again.
        run_requests=[dg.RunRequest(partition_key=f.month, run_key=f"{f.month}:{f.etag}") for f in changed],
        dynamic_partitions_requests=[trip_months.build_add_request(new)] if new else [],
        cursor=json.dumps(seen | {f.month: f.etag for f in changed}, sort_keys=True),
    )
