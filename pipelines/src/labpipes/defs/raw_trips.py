"""S1: the raw_trips asset.

One partition per month (partitions.trip_months), depending on trip_files. COPY the month's file into
Redshift with the LabRole attached to the cluster (`iam_role default`), so that re-running a month never
duplicates its rows. The landing columns come from contracts/trips.schema.yaml
(contracts.redshift_columns). Decision points: COPY vs Spectrum; dist and sort keys.
"""

import dagster as dg

from ..contracts import redshift_columns, trips_schema
from ..partitions import source_file, trip_months
from ..resources import DataBucket, RedshiftData

# Dist and sort keys (decisions/005): every write and read of this table is one month's source_file,
# so sorting on it lets the delete and stg_trips' select skip the other months' blocks. Applies when
# the table is created; changing it later takes an ALTER TABLE.
TABLE_KEYS = "diststyle auto sortkey (source_file)"


@dg.asset(partitions_def=trip_months, deps=["trip_files"], group_name="ingest", kinds={"redshift"}, pool="redshift")
def raw_trips(context: dg.AssetExecutionContext, redshift: RedshiftData, data_bucket: DataBucket) -> dg.MaterializeResult:
    month = context.partition_key
    file = source_file(month)
    columns = trips_schema()
    names = ", ".join(c.name.lower() for c in columns)
    # Parquet COPY maps columns by position, so it can't fill source_file: COPY into a temp table shaped
    # exactly like the contract, then swap the month's rows. One transaction: a failed COPY keeps the old rows.
    redshift.execute(
        "create schema if not exists ingest",
        f"create table if not exists ingest.raw_trips ({redshift_columns(columns)}, source_file varchar(64) not null) {TABLE_KEYS}",
        f"create temp table load_trips ({redshift_columns(columns)})",
        f"copy load_trips from '{data_bucket.trip_uri(month)}' iam_role default format as parquet",
        f"delete from ingest.raw_trips where source_file = '{file}'",
        f"insert into ingest.raw_trips ({names}, source_file) select {names}, '{file}' from load_trips",
    )
    rows = redshift.scalar(f"select count(*) from ingest.raw_trips where source_file = '{file}'")
    return dg.MaterializeResult(
        metadata={"rows": dg.MetadataValue.int(int(rows)), "source": data_bucket.trip_uri(month)}
    )
