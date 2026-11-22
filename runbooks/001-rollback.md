# Runbook: roll back the app (blue-green) and the model (champion alias)

Owner: akhilnathreddy · Last run: 2026-11-22 · Time to restore last run: 3.2 s (app, switch to riders on the old colour)

## When to use it

- **App:** right after a deploy, riders get errors, or `/version` shows the new tag and something that worked before doesn't.
- **Model:** right after a promotion, quotes are worse or slower than before ("the new model quotes 40 minutes for JFK to Midtown").

## Before you start

- GitHub access to run workflows on `akhilnathreddy/nyc-taxi-mlops-lab` (`gh auth status`). Use `-R akhilnathreddy/nyc-taxi-mlops-lab`: in this checkout some `gh` commands resolve to the upstream repo.
- Learner Lab session started, app host running (`scripts/health.sh`).
- For the model: you are the `production` environment's required reviewer.

## Steps

| # | Check (command) | Healthy looks like | If not: fix (command) | Took | Automated? |
| --- | --- | --- | --- | --- | --- |
| 1 | Which colour is live and what both run: `deploy/web.sh status` on the host, or the Status step of the last `cd` run | `live` is one colour; the other colour has a tag (the previous version) | App rollback: `gh workflow run rollback.yaml -R akhilnathreddy/nyc-taxi-mlops-lab`. It smoke-tests the other colour, switches, and reports how long riders took to reach it | 3.2 s switch, about 30 s for the run | yes: `rollback.yaml` |
| 2 | The other colour is also bad (`rollback.yaml` fails its smoke test) | | Redeploy a known-good tag to the idle colour: `gh workflow run cd.yaml -R ... -f tag=sha-<short sha>`. Same checks, then an automatic switch | about 1 min | yes: `cd.yaml` with a tag |
| 3 | Which model serving answers with: `curl -X POST http://<app_public_ip>/predict -H 'Content-Type: application/json' -d '{"pickup_zone_id": 132, "dropoff_zone_id": 230, "pickup_datetime": "2024-03-08T17:05:00"}'` | `model.alias` is `champion`, `model.version` is the one you meant to promote | Model rollback: find the outgoing champion (registered-model tag `previous_champion` in MLflow, or the `replaced_champion` tag on the current version), then `gh workflow run promote.yaml -R ... -f version=<that version>` and approve it. Serving reloads in place: the bad model answers until the old one is loaded, then the old one takes over with no gap | not run yet: needs a second champion (S8) | yes, behind your approval |

## Done when

- A rider's `POST /predict` from outside answers quickly, with `alias: champion` and the version you expect.
- `GET /version` shows the tag you rolled back to.
- `deploy/web.sh status`: `live` is the colour you rolled back to, the other colour still runs, and `serving.champion.version` is the expected model.

## What we automated, and what we left as a step

The app rollback is one workflow with no approval (record 011): the previous colour already passed its checks when it was live, and speed matters more than review when riders are affected. The model rollback goes through the same approval-gated `promote.yaml` as any promotion (record 010), because moving `champion` is always a reviewed click. Today there's only one gated version, so there's no previous champion to go back to; this row is tested for real in S8, when a retrain brings a second one.
