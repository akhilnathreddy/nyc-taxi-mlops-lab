"""Promotion (S3): point `champion` at an evaluated version and record the one it replaces.

Run only by .github/workflows/promote.yaml, after a required reviewer approved the run (contracts/mlflow.yaml:
champion moves only there). It runs inside the serving image, which already has MLflow, on the app host.

Env: MLFLOW_TRACKING_URI; VERSION (empty: the current challenger); PROMOTED_BY and RUN_URL (recorded).
A version is promotable if the pipeline evaluated it (decisions/010): it carries eval_report's tags. That
includes an earlier champion, so a model rollback (S8) is the same workflow with that version named.

Logs go to stderr; stdout is one JSON line: {"version", "outgoing", "changed"}.
"""

from __future__ import annotations

import json
import os
import sys
from datetime import datetime, timezone

from mlflow import MlflowClient
from mlflow.exceptions import MlflowException

NAME = "trip-duration"  # contracts/mlflow.yaml registered_model
EVALUATED = ("mae_min", "p95_latency_ms", "champion_mae_min")  # written by the pipeline's eval_report


def fail(msg: str) -> None:
    print(f"promotion refused: {msg}", file=sys.stderr)
    sys.exit(1)


def alias_version(client: MlflowClient, alias: str) -> str | None:
    try:
        return client.get_model_version_by_alias(NAME, alias).version
    except MlflowException:
        return None


def main() -> None:
    client = MlflowClient()
    requested = os.environ.get("VERSION", "").strip()
    if requested and not requested.isdigit():
        fail(f"version must be a number, got {requested!r}")
    version = requested or alias_version(client, "challenger")
    if not version:
        fail("no version named and no challenger alias: run the training pipeline first")

    try:
        mv = client.get_model_version(NAME, version)
    except MlflowException:
        fail(f"{NAME} v{version} does not exist")
    missing = [t for t in EVALUATED if t not in mv.tags]
    if missing:
        fail(f"v{version} was not evaluated by the pipeline (missing tags: {', '.join(missing)})")

    outgoing = alias_version(client, "champion")
    if outgoing == version:
        print(f"v{version} is already champion: nothing to move", file=sys.stderr)
        print(json.dumps({"version": version, "outgoing": outgoing, "changed": False}))
        return

    now = datetime.now(timezone.utc).isoformat(timespec="seconds")
    by, run = os.environ.get("PROMOTED_BY", "unknown"), os.environ.get("RUN_URL", "")
    # Record the outgoing champion before moving the alias: it is what a model rollback goes back to.
    client.set_registered_model_tag(NAME, "previous_champion", outgoing or "none")
    if outgoing:
        client.set_model_version_tag(NAME, outgoing, "replaced_by", version)
        client.set_model_version_tag(NAME, outgoing, "replaced_at", now)

    client.set_registered_model_alias(NAME, "champion", version)

    for k, v in {"promoted_at": now, "promoted_by": by, "promotion_run": run, "replaced_champion": outgoing or "none"}.items():
        client.set_model_version_tag(NAME, version, k, v)
    print(
        f"champion: v{outgoing or '-'} -> v{version} (mae_min {mv.tags['mae_min']}, "
        f"p95 {mv.tags['p95_latency_ms']} ms, compared against {mv.tags['champion_mae_min']})",
        file=sys.stderr,
    )
    print(json.dumps({"version": version, "outgoing": outgoing, "changed": True}))


if __name__ == "__main__":
    main()
