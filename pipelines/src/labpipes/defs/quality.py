"""S1: data-quality checks on stg_trips (nulls, ranges, duplicates, row counts).

Decision points: which checks block downstream and which only warn, and every threshold. Base them on
what real months look like (scripts/verify/results/tlc-stats-2024-01-04.md is the instructor's
baseline; measure your own in Redshift) and on what gameday's corrupt month would look like.

decisions/006: integrity failures block (the month never reaches zone_hour_stats); anomalies warn. Each
threshold is the most a month may have, as a % of its rows; the comments give 2024-01..04 as measured.
"""

import statistics
from dataclasses import dataclass

import dagster as dg

from ..partitions import check_month, trip_months
from ..resources import DataBucket, RedshiftData
from .staging import stg_trips


@dataclass(frozen=True)
class RateCheck:
    name: str
    bad: str  # SQL condition on a stg_trips row (s), with its pickup (zp) and dropoff (zd) zones joined
    max_pct: float
    blocking: bool
    description: str


RATE_CHECKS = [
    # Integrity: block.
    RateCheck("required_fields", "s.pickup_at is null or s.dropoff_at is null or s.pickup_zone_id is null or s.dropoff_zone_id is null",
              0.0, True, "No trip lacks its pickup or dropoff time or zone (0 in 2024-01..04)."),
    RateCheck("zones_in_lookup", "(s.pickup_zone_id is not null and zp.location_id is null) or (s.dropoff_zone_id is not null and zd.location_id is null)",
              0.0, True, "Every zone id is in taxi_zones (0 in 2024-01..04)."),
    RateCheck("pickups_in_month", "to_char(s.pickup_at, 'YYYY-MM') <> s.trip_month",
              0.01, True, "Pickups outside the file's month stay rare (max 0.0006% in 2024-01..04)."),
    # Anomalies: warn.
    RateCheck("passenger_count_nulls", "s.passenger_count is null",
              15.0, False, "Missing passenger counts (4.7% to 11.9% in 2024-01..04, rising)."),
    RateCheck("nonpositive_duration", "s.duration_min <= 0",
              0.1, False, "Dropoff at or before pickup (max 0.031% in 2024-01..04)."),
    RateCheck("over_3h", "s.duration_min > 180",
              0.2, False, "Trips over 3 hours (max 0.067% in 2024-01..04)."),
    RateCheck("zero_distance", "s.trip_distance <= 0",
              7.5, False, "Trips with no distance (max 2.4% in 2024-01..04)."),
    RateCheck("negative_fare", "s.fare_amount < 0",
              5.0, False, "Negative fares, i.e. refunds and disputes (max 1.6% in 2024-01..04)."),
]
DUPLICATES_MAX_PCT = 0.01  # warn: exact repeats of a trip (at most 1 row a month in 2024-01..04)
VOLUME_MIN_SHARE = 0.5  # block: rows below half the median of the other loaded months (2.96M..3.58M)


def _severity(blocking: bool) -> dg.AssetCheckSeverity:
    return dg.AssetCheckSeverity.ERROR if blocking else dg.AssetCheckSeverity.WARN


def _rate_check(spec: RateCheck) -> dg.AssetChecksDefinition:
    @dg.asset_check(asset=stg_trips, name=spec.name, partitions_def=trip_months, blocking=spec.blocking,
                    description=f"{spec.description} {'Blocks' if spec.blocking else 'Warns'} above {spec.max_pct}%.")
    def _check(context: dg.AssetCheckExecutionContext, redshift: RedshiftData) -> dg.AssetCheckResult:
        month = check_month(context.partition_key)
        s = redshift.query(
            f"select count(*) as rows, sum(case when {spec.bad} then 1 else 0 end) as bad from staging.stg_trips s "
            "left join ingest.taxi_zones zp on zp.location_id = s.pickup_zone_id "
            "left join ingest.taxi_zones zd on zd.location_id = s.dropoff_zone_id "
            f"where s.trip_month = '{month}'"
        )[0]
        rows, bad = int(s["rows"]), int(s["bad"] or 0)
        pct = 100.0 * bad / rows if rows else 0.0
        return dg.AssetCheckResult(
            passed=bad <= rows * spec.max_pct / 100,
            severity=_severity(spec.blocking),
            description=f"{bad} of {rows} rows ({pct:.4f}%), limit {spec.max_pct}%",
            metadata={"bad_rows": dg.MetadataValue.int(bad), "pct": dg.MetadataValue.float(pct), "max_pct": spec.max_pct},
        )

    return _check


rate_checks = [_rate_check(spec) for spec in RATE_CHECKS]


@dg.asset_check(asset=stg_trips, partitions_def=trip_months, blocking=True,
                description="stg_trips has exactly the rows in the file's Parquet footer: nothing lost or duplicated in the load.")
def row_count_matches_file(context: dg.AssetCheckExecutionContext, redshift: RedshiftData, data_bucket: DataBucket) -> dg.AssetCheckResult:
    month = check_month(context.partition_key)
    expected = data_bucket.footer(month).num_rows
    loaded = int(redshift.scalar(f"select count(*) from staging.stg_trips where trip_month = '{month}'"))
    return dg.AssetCheckResult(
        passed=loaded == expected,
        severity=dg.AssetCheckSeverity.ERROR,
        description=f"{loaded} rows loaded, file has {expected}",
        metadata={"loaded": dg.MetadataValue.int(loaded), "file_rows": dg.MetadataValue.int(expected)},
    )


@dg.asset_check(asset=stg_trips, partitions_def=trip_months, blocking=True,
                description=f"The month has at least {VOLUME_MIN_SHARE:.0%} of the median row count of the other loaded months (a truncated file).")
def month_volume(context: dg.AssetCheckExecutionContext, redshift: RedshiftData) -> dg.AssetCheckResult:
    month = check_month(context.partition_key)
    counts = {r["trip_month"]: int(r["n"]) for r in redshift.query(
        "select trip_month, count(*) as n from staging.stg_trips group by trip_month")}
    rows = counts.pop(month, 0)
    if not counts:
        return dg.AssetCheckResult(passed=True, severity=dg.AssetCheckSeverity.ERROR,
                                   description=f"{rows} rows; no other month loaded to compare with")
    floor = VOLUME_MIN_SHARE * statistics.median(counts.values())
    return dg.AssetCheckResult(
        passed=rows >= floor,
        severity=dg.AssetCheckSeverity.ERROR,
        description=f"{rows} rows, floor {floor:.0f} ({VOLUME_MIN_SHARE:.0%} of the median of {len(counts)} other month(s))",
        metadata={"rows": dg.MetadataValue.int(rows), "floor": dg.MetadataValue.int(int(floor))},
    )


@dg.asset_check(asset=stg_trips, partitions_def=trip_months, blocking=False,
                description=f"Exact repeats of a trip (same vendor, times, zones and total). Warns above {DUPLICATES_MAX_PCT}%.")
def duplicate_trips(context: dg.AssetCheckExecutionContext, redshift: RedshiftData) -> dg.AssetCheckResult:
    month = check_month(context.partition_key)
    s = redshift.query(
        "select coalesce(sum(n - 1), 0) as dups, coalesce(sum(n), 0) as rows from ("
        "select count(*) as n from staging.stg_trips "
        f"where trip_month = '{month}' "
        "group by vendor_id, pickup_at, dropoff_at, pickup_zone_id, dropoff_zone_id, total_amount)"
    )[0]
    dups, rows = int(s["dups"]), int(s["rows"])
    pct = 100.0 * dups / rows if rows else 0.0
    return dg.AssetCheckResult(
        passed=dups <= rows * DUPLICATES_MAX_PCT / 100,
        severity=dg.AssetCheckSeverity.WARN,
        description=f"{dups} duplicate row(s) of {rows} ({pct:.4f}%), limit {DUPLICATES_MAX_PCT}%",
        metadata={"duplicate_rows": dg.MetadataValue.int(dups), "pct": dg.MetadataValue.float(pct)},
    )
