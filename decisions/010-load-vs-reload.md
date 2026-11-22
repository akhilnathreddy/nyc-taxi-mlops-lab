# 010: Serving picks up a new champion by reloading in place, triggered by the promotion workflow

Stage: S3 · Date: 2026-11-22 · Author: akhilnathreddy · Drafted by agent: yes

## Choice

`serving-champion` loads `models:/trip-duration@champion` when it starts, and after that changes model only when told to: `promote.yaml` moves the alias, then calls `POST /reload` (`deploy/web.sh reload champion`). The container resolves the alias again, loads the new version next to the old one, and swaps; the old model answers every request until the new one is ready. The workflow then checks that `/predict` through the live colour answers with `alias: champion` and the promoted version.

Which versions `promote.yaml` accepts is part of the same choice: any version the pipeline evaluated (it carries `eval_report`'s `mae_min`, `p95_latency_ms` and `champion_mae_min` tags). By default that is the current `challenger`. Naming an earlier champion is how the model gets rolled back (S8), and the outgoing champion is recorded before the alias moves (registered-model tag `previous_champion`, version tags `replaced_by` / `replaced_at`).

## Rejected alternative

Load at start-up only: `promote.yaml` restarts `serving-champion`, so the model is only ever loaded at boot. One code path and nothing swapped inside a running process, but while it loads, Traefik's `/model` health check marks it down and the app quotes the static median.

## Why

<!-- Draft from the evidence below: rewrite in your own words, as for 004–006. -->

A promotion is supposed to be invisible to riders except for better quotes. With a restart, every promotion (and every model rollback, which is the moment things are already going wrong) would put riders on the 12.25-minute static quote for as long as the model takes to load from S3 through MLflow. The static quote's MAE on the 2024-04 holdout is 8.61 min against 3.96 for v1 (record 007), so even a short gap is a visibly worse quote, not just a slower one. Reload keeps the old model answering, so there is no gap. Its costs: the container briefly holds two models in memory, and if the new one fails to load, the old one stays and the workflow fails at the `/reload` or `/predict` step, which is what I want.

The alias still decides what serving answers with, not a version number in a config file: a container that restarts for any other reason (Start Lab, a crash, a serving deploy) loads whatever `champion` points at, so the two paths can't disagree for long.

Evidence from the first promotion (run 44996499177, waited for my approval in `production`): the alias moved from none to v1 (MAE 3.6376 against the baseline's 3.9563, p95 3.23 ms), and `/predict` from outside answered `{"duration_minutes": 64.19, "model": {"name": "trip-duration", "version": "1", "alias": "champion"}}`. `/reload` answered `{"version": "1", "previous_version": "1", "changed": false}`: `serving-champion` had already loaded v1 by itself between the alias moving and the reload call. So a container that has no model yet keeps trying the alias without being told to. Once a champion is loaded, only `/reload` (or a restart) changes it. The reload step is what makes the swap happen when the promotion runs instead of whenever the container next looks. S8's second promotion is where `changed: true` gets tested for real.

## What would show this was wrong

- A promotion run where `/reload` succeeds but `/predict` keeps answering with the old version or the static median, or where the app host runs out of memory during the swap.
- A serving container that restarts and loads a different version than the one `/model` reported before, meaning the alias moved without a reload (someone moved it outside `promote.yaml`).
