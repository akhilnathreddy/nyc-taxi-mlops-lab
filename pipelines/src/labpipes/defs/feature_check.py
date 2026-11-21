"""S2: the feature_contract check on trip_features.

contracts/features.yaml lists the model's inputs, label and the post-trip columns that must never be
inputs; contracts/mlflow.yaml says this check blocks. Decide what "matches" means: column names,
types, value ranges. Gameday E1 will test it.

Matches means all three: the table has exactly the contract's columns (keys, inputs, label; so neither a
forbidden post-trip column nor the derived est_distance_miles), each with the contract's type, and the
month's values are inside every range the contract gives.
"""

import dagster as dg

from ..contracts import features_contract
from ..partitions import check_month, trip_months
from ..resources import RedshiftData
from .features import trip_features


def expected_columns(contract: dict) -> dict[str, dict]:
    return {c["name"]: c for c in [*contract["keys"], *contract["inputs"], contract["label"]]}


def column_problems(found: dict[str, str], contract: dict) -> list[str]:
    """found: column name -> Redshift type, e.g. {"pickup_hour": "smallint", "trip_month": "char(7)"}."""
    expected = expected_columns(contract)
    forbidden = {f.lower() for f in contract["forbidden"]}
    problems = [f"forbidden post-trip column {c!r}" for c in found if c in forbidden]
    problems += [f"column {c!r} is not in the contract" for c in found if c not in expected and c not in forbidden]
    problems += [f"missing column {c!r}" for c in expected if c not in found]
    problems += [f"{c}: {found[c]}, contract has {e['type']}" for c, e in expected.items()
                 if c in found and found[c] != e["type"].lower()]
    return problems


def range_violations_sql(contract: dict, month: str) -> str:
    """One row: per ranged column, how many of the month's rows fall outside the contract's range."""
    terms = []
    for c in [*contract["inputs"], contract["label"]]:
        if "range" not in c:
            continue
        lo, hi = c["range"]
        low = f"{c['name']} <= {lo}" if c.get("exclusive_min") else f"{c['name']} < {lo}"
        terms.append(f"sum(case when {c['name']} is null or {low} or {c['name']} > {hi} then 1 else 0 end) as {c['name']}")
    return f"select {', '.join(terms)} from {contract['table']} where trip_month = '{check_month(month)}'"


@dg.asset_check(asset=trip_features, partitions_def=trip_months, blocking=True,
                description="trip_features has exactly the columns and types of contracts/features.yaml, and values inside its ranges.")
def feature_contract(context: dg.AssetCheckExecutionContext, redshift: RedshiftData) -> dg.AssetCheckResult:
    contract = features_contract()
    schema, table = contract["table"].split(".")
    rows = redshift.query(
        "select column_name, data_type, character_maximum_length from information_schema.columns "
        f"where table_schema = '{schema}' and table_name = '{table}' order by ordinal_position"
    )
    found = {r["column_name"]: (f"char({r['character_maximum_length']})" if r["data_type"] == "character" else r["data_type"])
             for r in rows}
    problems = column_problems(found, contract)
    if not problems:
        violations = redshift.query(range_violations_sql(contract, context.partition_key))[0]
        problems += [f"{c}: {int(n)} row(s) outside the contract's range" for c, n in violations.items() if int(n or 0)]
    return dg.AssetCheckResult(
        passed=not problems,
        severity=dg.AssetCheckSeverity.ERROR,
        description="; ".join(problems) if problems else "columns, types and ranges match the contract",
        metadata={"problems": dg.MetadataValue.json(problems), "columns": dg.MetadataValue.json(found)},
    )
