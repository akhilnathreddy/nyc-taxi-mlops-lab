"""S1: the schema gate, the idempotent load and the sensor, against the fakes."""

import json

import dagster as dg
import pytest
from fakes import LOG, fake_bucket, fake_redshift, schema_2023, schema_2025

from labpipes.contracts import trips_schema
from labpipes.defs.raw_trips import raw_trips
from labpipes.defs.schema_check import schema_contract
from labpipes.defs.sensor import trip_files_sensor
from labpipes.defs.trip_files import trip_files


def run_month(month, columns):
    with dg.instance_for_test() as instance:
        instance.add_dynamic_partitions("trip_months", [month])
        result = dg.materialize(
            [trip_files, schema_contract, raw_trips],
            partition_key=month,
            instance=instance,
            resources={"redshift": fake_redshift(), "data_bucket": fake_bucket({month: ("e", columns)})},
            raise_on_error=False,
        )
        return result.get_asset_check_evaluations()[0], any(s.startswith("copy ") for s in LOG)


def test_contract_file_passes_and_is_copied():
    check, copied = run_month("2024-01", trips_schema())
    assert check.passed and copied


@pytest.mark.parametrize("columns", [schema_2023(), schema_2025()], ids=["types-changed", "column-appended"])
def test_schema_drift_blocks_the_copy(columns):
    check, copied = run_month("2024-02", columns)
    assert not check.passed and not copied


def test_reload_replaces_the_month_in_one_transaction():
    run_month("2024-03", trips_schema())
    load = LOG[: LOG.index(next(s for s in LOG if s.startswith("select count")))]
    delete = next(i for i, s in enumerate(load) if s.startswith("delete from ingest.raw_trips"))
    insert = next(i for i, s in enumerate(load) if s.startswith("insert into ingest.raw_trips"))
    assert "where source_file = 'yellow_tripdata_2024-03.parquet'" in load[delete] and delete < insert


def test_sensor_runs_new_and_replaced_files_once():
    with dg.instance_for_test() as instance:

        def tick(files, cursor):
            ctx = dg.build_sensor_context(instance=instance, cursor=cursor, resources={"data_bucket": fake_bucket(files)})
            result = trip_files_sensor(ctx)
            if isinstance(result, dg.SkipReason):
                return [], cursor
            for req in result.dynamic_partitions_requests:
                instance.add_dynamic_partitions("trip_months", list(req.partition_keys))
            return [r.run_key for r in result.run_requests], result.cursor

        schema = trips_schema()
        runs, cursor = tick({"2024-01": ("a", schema), "2024-02": ("b", schema)}, None)
        assert runs == ["2024-01:a", "2024-02:b"]
        assert instance.get_dynamic_partitions("trip_months") == ["2024-01", "2024-02"]
        assert tick({"2024-01": ("a", schema), "2024-02": ("b", schema)}, cursor)[0] == []
        runs, cursor = tick({"2024-01": ("a", schema), "2024-02": ("c", schema)}, cursor)
        assert runs == ["2024-02:c"] and json.loads(cursor) == {"2024-01": "a", "2024-02": "c"}
