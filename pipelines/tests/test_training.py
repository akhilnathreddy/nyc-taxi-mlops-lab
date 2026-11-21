"""S2: the feature contract, and train_model end to end on synthetic trips with a local MLflow."""

import dagster as dg
import pytest
from fakes import LocalArtifacts, unloading_redshift

from labpipes.contracts import features_contract, mlflow_contract
from labpipes.defs import training
from labpipes.defs.feature_check import column_problems, range_violations_sql
from labpipes.resources import MlflowTracking

GOOD = {"trip_month": "char(7)", "pickup_zone_id": "integer", "dropoff_zone_id": "integer",
        "pickup_hour": "smallint", "pickup_dow": "smallint", "duration_min": "double precision"}


def test_contract_table_matches():
    assert column_problems(GOOD, features_contract()) == []


@pytest.mark.parametrize("found, expected", [
    (GOOD | {"trip_distance": "double precision"}, "forbidden post-trip column 'trip_distance'"),
    (GOOD | {"est_distance_miles": "double precision"}, "column 'est_distance_miles' is not in the contract"),
    ({k: v for k, v in GOOD.items() if k != "pickup_dow"}, "missing column 'pickup_dow'"),
    (GOOD | {"pickup_hour": "integer"}, "pickup_hour: integer, contract has smallint"),
], ids=["leaky", "derived-as-column", "missing", "type-changed"])
def test_contract_mismatches_are_named(found, expected):
    assert expected in column_problems(found, features_contract())


def test_ranges_come_from_the_contract():
    sql = range_violations_sql(features_contract(), "2024-03")
    assert "pickup_zone_id < 1 or pickup_zone_id > 263" in sql
    assert "duration_min <= 0 or duration_min > 180" in sql  # exclusive_min
    assert sql.endswith("where trip_month = '2024-03'")


def test_gate_needs_gain_on_every_front(monkeypatch):
    monkeypatch.setattr(training, "P95_LATENCY_BUDGET_MS", 50.0)
    incumbent = {"mae_min": 5.0, "mae_min.airport": 10.0, "p95_latency_ms": 1.0}
    assert training.gate_failures({"mae_min": 4.8, "mae_min.airport": 10.4, "p95_latency_ms": 5.0}, incumbent) == []
    assert training.gate_failures({"mae_min": 4.95, "mae_min.airport": 9.0, "p95_latency_ms": 5.0}, incumbent)  # < 2% gain
    assert training.gate_failures({"mae_min": 4.5, "mae_min.airport": 10.6, "p95_latency_ms": 5.0}, incumbent)  # airport 6% worse
    assert training.gate_failures({"mae_min": 4.5, "mae_min.airport": 9.0, "p95_latency_ms": 60.0}, incumbent)  # too slow
    monkeypatch.setattr(training, "P95_LATENCY_BUDGET_MS", None)
    assert training.gate_failures({"mae_min": 1.0, "p95_latency_ms": 0.1}, incumbent)  # no budget: fails closed


def train(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("GIT_SHA", "abc1234")
    resources = {
        "redshift": unloading_redshift(str(tmp_path / "s3")),
        "artifacts": LocalArtifacts(bucket="artifacts", root=str(tmp_path / "s3")),
        "tracking": MlflowTracking(tracking_uri=f"sqlite:///{tmp_path}/mlflow.db"),
    }
    with dg.instance_for_test() as instance:
        result = dg.materialize(
            [training.training_set, training.trained_model, training.eval_report, training.beats_champion, training.challenger],
            instance=instance, resources=resources, raise_on_error=False,
        )
        built = {e.event_specific_data.materialization.asset_key.to_user_string() for e in result.get_asset_materialization_events()}
        gate = result.get_asset_check_evaluations()[0]
    from mlflow import MlflowClient

    return built, gate, MlflowClient(f"sqlite:///{tmp_path}/mlflow.db")


def test_train_model_registers_a_tagged_version_and_sets_challenger(tmp_path, monkeypatch):
    monkeypatch.setattr(training, "P95_LATENCY_BUDGET_MS", 1000.0)
    built, gate, client = train(tmp_path, monkeypatch)
    name = mlflow_contract()["registered_model"]
    assert gate.passed and "challenger" in built
    aliases = client.get_registered_model(name).aliases
    assert {k: str(v) for k, v in aliases.items()} == {"challenger": "1"}  # never champion
    tags = client.get_model_version(name, "1").tags
    assert set(mlflow_contract()["version_tags"]) <= set(tags)
    assert tags["training_window"] == "2024-01..2024-03" and tags["holdout_month"] == "2024-04" and tags["git_sha"] == "abc1234"
    assert float(tags["mae_min"]) < float(tags["champion_mae_min"])


def test_no_latency_budget_keeps_the_alias_unset(tmp_path, monkeypatch):
    monkeypatch.setattr(training, "P95_LATENCY_BUDGET_MS", None)
    built, gate, client = train(tmp_path, monkeypatch)
    assert not gate.passed and "challenger" not in built
    assert client.get_registered_model(mlflow_contract()["registered_model"]).aliases == {}
