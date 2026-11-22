# 011: The blue-green switch is automatic once the health check and smoke test pass

Stage: S3 · Date: 2026-11-22 · Author: akhilnathreddy · Drafted by agent: yes

## Choice

`cd.yaml` deploys every green CI run on `main` to the idle colour and flips traffic to it with no person in the loop, but only after three checks pass on that colour, in order:

1. The container's own Docker health check (`/healthz`): `docker compose up --wait` returns only when it is healthy.
2. `/healthz` through Traefik, pinned to the colour (`X-Lab-Color`).
3. The smoke test (`deploy/web.sh smoke`): `/version` reports this commit's sha and image tag, and `/predict` answers.

Any failure stops the job before `deploy/web.sh switch`, so riders stay on the live colour and the broken one gets no traffic. After the switch the job checks that unpinned traffic reaches the new tag. The old colour keeps running, and `rollback.yaml` switches back to it without building or deploying anything.

## Rejected alternative

Wait for approval: the switch job runs in an environment with me as required reviewer, so a person looks at the idle colour before riders get it. Safer against a change that passes the checks but is still wrong, but every merge waits for me, and nothing I would look at by hand isn't already in the smoke test.

## Why

<!-- Draft from the evidence below: rewrite in your own words, as for 004–006. -->

Code already passed review and CI before it reaches `main`; a second approval at deploy time would mostly be me clicking through the same `/version` and `/predict` the smoke test already checks. What the switch needs to protect against is a colour that doesn't start or doesn't answer, and those are exactly what the checks catch. Because the old colour is still running, a bad switch costs one `rollback.yaml` run, measured at `<rollback ms>` ms from switch to riders on the old version (run `<rollback run>`), not a redeploy. The model has its own human gate (`promote.yaml`, record 010), so automatic app deploys never change which model riders get.

Evidence from the first deploy (run 44996417282): blue was healthy 11 s after it started, the smoke test passed, and riders were on it about 2 s after the switch.

The known gap: the smoke test checks that `/predict` answers, not which model answered. A colour that can't reach serving falls back to the static median and still passes. I accept that for S3 because serving runs separately from the app colours, so an app deploy rarely changes it; if it starts happening, the smoke test should require `model.alias == "champion"` once there is one.

## What would show this was wrong

- A switch that passed all three checks but broke riders (errors, or quotes from the static median when a champion exists) before anyone noticed.
- Needing `rollback.yaml` more than occasionally: the checks are too weak for an automatic switch.
- Record 002 says rollback redeploys an earlier tag. From S3 on, the first move is `rollback.yaml` (switch colours); redeploying a tag is for when neither colour is good.
