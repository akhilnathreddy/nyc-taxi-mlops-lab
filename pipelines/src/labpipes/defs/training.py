"""S2: training_set, trained_model, eval_report, the challenger gate and the challenger asset.

- training_set: UNLOAD a window of staging.trip_features (and the holdout month) to the artifact bucket.
  The zone-pair distance lookup (contracts/features.yaml, est_distance_miles) comes from the window only.
- trained_model: fit tripmodel.LightGBMModel (the given v2), log it to MLflow as a pyfunc with
  tripmodel.model_signature() and the tripmodel package bundled, register a version of the model named
  in contracts/mlflow.yaml, and tag it as that contract says.
- eval_report: tripmodel.evaluate the new version and the champion (or the v1 baseline before there is
  one) on the same holdout; log the metrics.
- A blocking check that guards a `challenger` asset, which sets the alias. The pipeline never moves
  `champion`.
Decision points: what stays in the notebook; the promotion metric and margin; the training window.
"""

import os
from pathlib import Path

import dagster as dg

import tripmodel
from tripmodel import BaselineModel, LightGBMModel, evaluate, model_signature

from ..contracts import features_contract, mlflow_contract
from ..partitions import check_month
from ..resources import ArtifactBucket, MlflowTracking, RedshiftData

# Training window (decisions/): the latest month in trip_features is the holdout; the WINDOW_MONTHS
# before it train. None: every earlier month.
WINDOW_MONTHS: int | None = None

# Promotion (decisions/): a new version must beat the incumbent (champion, or the v1 baseline before
# there is one) on the same holdout: overall MAE at least MIN_MAE_GAIN lower, no slice more than
# MAX_SLICE_LOSS worse, and single-row p95 latency within the budget.
MIN_MAE_GAIN = 0.02
MAX_SLICE_LOSS = 0.05
SLICES = ("airport", "manhattan", "outer", "night")
P95_LATENCY_BUDGET_MS: float | None = 25.0  # the model's share of /predict; None makes the gate fail closed

COLUMNS = "pickup_zone_id, dropoff_zone_id, pickup_hour, pickup_dow, duration_min"


def latest_metadata(instance: dg.DagsterInstance, asset: str) -> dict:
    """The metadata of an asset's latest materialization, as plain values."""
    event = instance.get_latest_materialization_event(dg.AssetKey(asset))
    if event is None:
        raise dg.Failure(f"{asset} has never been materialized: run train_model from training_set")
    return {k: v.value for k, v in event.asset_materialization.metadata.items()}


def gate_failures(new: dict, incumbent: dict) -> list[str]:
    """Why a version may not become challenger; empty when it may."""
    failures = []
    if P95_LATENCY_BUDGET_MS is None:
        failures.append("no latency budget decided (P95_LATENCY_BUDGET_MS)")
    elif new["p95_latency_ms"] > P95_LATENCY_BUDGET_MS:
        failures.append(f"p95 latency {new['p95_latency_ms']:.2f} ms over the {P95_LATENCY_BUDGET_MS} ms budget")
    bar = incumbent["mae_min"] * (1 - MIN_MAE_GAIN)
    if new["mae_min"] > bar:
        failures.append(f"MAE {new['mae_min']:.4f} not at least {MIN_MAE_GAIN:.0%} below {incumbent['mae_min']:.4f} (needs <= {bar:.4f})")
    for s in SLICES:
        key = f"mae_min.{s}"
        if key in new and key in incumbent and new[key] > incumbent[key] * (1 + MAX_SLICE_LOSS):
            failures.append(f"{s} MAE {new[key]:.4f} more than {MAX_SLICE_LOSS:.0%} worse than {incumbent[key]:.4f}")
    return failures


@dg.asset(deps=["trip_features"], group_name="model", kinds={"redshift", "s3"}, pool="redshift")
def training_set(context: dg.AssetExecutionContext, redshift: RedshiftData, artifacts: ArtifactBucket) -> dg.MaterializeResult:
    months = [check_month(r["trip_month"].strip()) for r in
              redshift.query("select distinct trip_month from staging.trip_features order by trip_month")]
    if len(months) < 2:
        raise dg.Failure(f"need a window and a holdout month, trip_features has {months}")
    holdout = months[-1]
    window = months[:-1] if WINDOW_MONTHS is None else months[:-1][-WINDOW_MONTHS:]
    prefix = f"training/{context.run_id}/"

    # UNLOAD's query is a quoted string, so its literals are doubled: ''2024-01''.
    in_window = ", ".join(f"''{m}''" for m in window)

    def unload(select: str, part: str) -> str:
        return f"unload ('{select}') to '{artifacts.uri(prefix + part + '/')}' iam_role default format as parquet allowoverwrite"

    redshift.execute(unload(f"select {COLUMNS} from staging.trip_features where trip_month in ({in_window})", "train"))
    redshift.execute(unload(f"select {COLUMNS} from staging.trip_features where trip_month = ''{holdout}''", "holdout"))
    # est_distance_miles: the zone pair's median distance over the window only, never the holdout.
    redshift.execute(unload(
        "select pickup_zone_id, dropoff_zone_id, median(trip_distance) as est_distance_miles from staging.stg_trips "
        f"where trip_month in ({in_window}) and trip_distance > 0 and duration_min > 0 and duration_min <= 180 "
        "group by pickup_zone_id, dropoff_zone_id", "distances"))

    window_sql = ", ".join(f"'{m}'" for m in window)
    n = redshift.query(
        f"select sum(case when trip_month in ({window_sql}) then 1 else 0 end) as train, "
        f"sum(case when trip_month = '{holdout}' then 1 else 0 end) as holdout from staging.trip_features"
    )[0]
    return dg.MaterializeResult(metadata={
        "prefix": prefix,
        "training_window": f"{window[0]}..{window[-1]}",
        "holdout_month": holdout,
        "train_rows": dg.MetadataValue.int(int(n["train"])),
        "holdout_rows": dg.MetadataValue.int(int(n["holdout"])),
    })


@dg.asset(deps=[training_set], group_name="model", kinds={"mlflow"})
def trained_model(context: dg.AssetExecutionContext, artifacts: ArtifactBucket, tracking: MlflowTracking) -> dg.MaterializeResult:
    import mlflow

    ts = latest_metadata(context.instance, "training_set")
    train = artifacts.read_parquet(ts["prefix"] + "train/")
    distances = artifacts.read_parquet(ts["prefix"] + "distances/")
    client = tracking.client()
    name = mlflow_contract()["registered_model"]
    with mlflow.start_run(run_name=f"v2 {ts['training_window']}") as run:
        mlflow.log_params({"model": "LightGBMModel", "training_window": ts["training_window"],
                           "holdout_month": ts["holdout_month"], "train_rows": len(train), **LightGBMModel.DEFAULT_PARAMS})
        model = LightGBMModel().fit(train, distances)
        info = mlflow.pyfunc.log_model(name="model", python_model=model, signature=model_signature(),
                                       code_paths=[str(Path(tripmodel.__file__).parent)], registered_model_name=name)
    version = str(info.registered_model_version)
    tags = {
        "training_window": ts["training_window"],
        "holdout_month": ts["holdout_month"],
        "features_version": str(features_contract()["version"]),
        "git_sha": os.environ.get("GIT_SHA", "unknown"),
    }
    for k, v in tags.items():
        client.set_model_version_tag(name, version, k, v)
    return dg.MaterializeResult(metadata={"version": version, "run_id": run.info.run_id, **tags})


@dg.asset(deps=[trained_model], group_name="model", kinds={"mlflow"})
def eval_report(context: dg.AssetExecutionContext, redshift: RedshiftData, artifacts: ArtifactBucket,
                tracking: MlflowTracking) -> dg.MaterializeResult:
    import mlflow

    ts = latest_metadata(context.instance, "training_set")
    tm = latest_metadata(context.instance, "trained_model")
    holdout = artifacts.read_parquet(ts["prefix"] + "holdout/")
    boroughs = {int(r["location_id"]): r["borough"] for r in redshift.query("select location_id, borough from ingest.taxi_zones")}
    client = tracking.client()
    name = mlflow_contract()["registered_model"]

    # The new version as serving will load it: the registered pyfunc, not the object in memory.
    new = evaluate(mlflow.pyfunc.load_model(f"models:/{name}/{tm['version']}").predict, holdout, boroughs)
    aliases = client.get_registered_model(name).aliases
    if "champion" in aliases:
        against = f"champion v{aliases['champion']}"
        incumbent = evaluate(mlflow.pyfunc.load_model(f"models:/{name}@champion").predict, holdout, boroughs)
    else:
        against = "v1 baseline (no champion yet)"
        baseline = BaselineModel().fit(artifacts.read_parquet(ts["prefix"] + "train/"), artifacts.read_parquet(ts["prefix"] + "distances/"))
        incumbent = evaluate(lambda df: baseline.predict(None, df), holdout, boroughs)

    metrics = {k: v for k, v in new.items() if k in mlflow_contract()["metrics"]} | {"champion_mae_min": incumbent["mae_min"]}
    for k, v in metrics.items():
        client.log_metric(tm["run_id"], k, v)
    for k in ("mae_min", "p95_latency_ms", "champion_mae_min"):
        client.set_model_version_tag(name, tm["version"], k, f"{metrics[k]:.4f}")
    return dg.MaterializeResult(metadata={
        "version": tm["version"],
        "against": against,
        "mae_min": dg.MetadataValue.float(new["mae_min"]),
        "champion_mae_min": dg.MetadataValue.float(incumbent["mae_min"]),
        "p95_latency_ms": dg.MetadataValue.float(new["p95_latency_ms"]),
        "new": dg.MetadataValue.json(new),
        "incumbent": dg.MetadataValue.json(incumbent),
    })


@dg.asset_check(asset=eval_report, blocking=True,
                description=f"The new version beats the incumbent on the holdout: MAE at least {MIN_MAE_GAIN:.0%} lower, "
                            f"no slice more than {MAX_SLICE_LOSS:.0%} worse, p95 latency within budget.")
def beats_champion(context: dg.AssetCheckExecutionContext) -> dg.AssetCheckResult:
    report = latest_metadata(context.instance, "eval_report")
    failures = gate_failures(report["new"], report["incumbent"])
    return dg.AssetCheckResult(
        passed=not failures,
        severity=dg.AssetCheckSeverity.ERROR,
        description="; ".join(failures) if failures else f"v{report['version']} beats the {report['against']}",
        metadata={"version": report["version"], "against": report["against"], "failures": dg.MetadataValue.json(failures)},
    )


@dg.asset(deps=[eval_report], group_name="model", kinds={"mlflow"})
def challenger(context: dg.AssetExecutionContext, tracking: MlflowTracking) -> dg.MaterializeResult:
    """Points the challenger alias at the evaluated version. Never touches champion."""
    report = latest_metadata(context.instance, "eval_report")
    # The blocking check stops this asset in a train_model run; this guards a run that selects it alone.
    failures = gate_failures(report["new"], report["incumbent"])
    if failures:
        raise dg.Failure(f"v{report['version']} did not pass the gate: {'; '.join(failures)}")
    name = mlflow_contract()["registered_model"]
    tracking.client().set_registered_model_alias(name, "challenger", report["version"])
    return dg.MaterializeResult(metadata={"version": report["version"], "against": report["against"]})


train_model = dg.define_asset_job("train_model", selection=dg.AssetSelection.assets("training_set").downstream())
