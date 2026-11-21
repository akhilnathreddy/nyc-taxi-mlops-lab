"""S1: the schema_contract check on trip_files.

Compare the landed file's Parquet footer (the DataBucket resource reads it) with
contracts/trips.schema.yaml, before raw_trips copies anything. contracts/platform.yaml says this check
is blocking. Patterns: pipelines/reference/patterns.py. Decision point: what counts as a mismatch?
"""

from dataclasses import asdict

import dagster as dg

from ..contracts import Column, trips_schema
from ..partitions import trip_months
from ..resources import DataBucket
from .trip_files import trip_files


def mismatches(found: list[Column], expected: list[Column]) -> list[str]:
    """Differences that would break or skew a positional COPY, as the contract defines them: column
    count, then at each position the name (case-insensitive) and the exact Parquet type."""
    problems = []
    if len(found) != len(expected):
        problems.append(f"{len(found)} columns, contract has {len(expected)}")
    for i, (f, e) in enumerate(zip(found, expected, strict=False)):  # extra/missing columns: below
        if f.name.lower() != e.name.lower():
            problems.append(f"column {i + 1}: {f.name!r}, contract has {e.name!r}")
        elif f.type != e.type:
            problems.append(f"column {i + 1} ({e.name}): {f.type}, contract has {e.type}")
    for i, c in enumerate(found[len(expected) :], start=len(expected)):
        problems.append(f"column {i + 1}: unexpected {c.name!r} ({c.type})")
    for i, c in enumerate(expected[len(found) :], start=len(found)):
        problems.append(f"column {i + 1}: missing {c.name!r} ({c.type})")
    return problems


@dg.asset_check(
    asset=trip_files,
    partitions_def=trip_months,
    blocking=True,
    description="The file's Parquet footer matches contracts/trips.schema.yaml, before anything is copied.",
)
def schema_contract(context: dg.AssetCheckExecutionContext, data_bucket: DataBucket) -> dg.AssetCheckResult:
    found = data_bucket.footer(context.partition_key).columns
    problems = mismatches(found, trips_schema())
    return dg.AssetCheckResult(
        passed=not problems,
        severity=dg.AssetCheckSeverity.ERROR,
        description="; ".join(problems) if problems else "matches the contract",
        metadata={
            "mismatches": dg.MetadataValue.int(len(problems)),
            "problems": dg.MetadataValue.json(problems),
            "columns": dg.MetadataValue.json([asdict(c) for c in found]),
        },
    )
