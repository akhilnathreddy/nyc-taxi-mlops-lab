# 001: Runner credentials: the instance profile

Stage: S0 · Date: 2026-11-21 · Author: akhilnathreddy · Drafted by agent: yes

## Choice

The self-hosted `lab-app` runner uses the app host's instance profile (`LabInstanceProfile`, i.e. `LabRole`). No AWS credentials are stored in GitHub secrets; CI and CD authenticate to GHCR with `GITHUB_TOKEN` only.

## Rejected alternative

Static Learner Lab session credentials (the AWS Details keys) stored as GitHub repository secrets and passed to the runner's jobs.

## Why

- Learner Lab session keys expire at every session refresh. With secrets, CD silently breaks after each Start Lab until I re-run `scripts/gh-secrets.sh`; with the instance profile the host gets fresh credentials from IMDS automatically, so the stack and the runner come back with no action from me.
- Nothing to leak: the repo is public, and keys sitting in repo settings are one misconfigured workflow (`echo`, debug logging, a malicious PR) away from exposure. The instance profile's credentials never leave the host.
- The trade-off I accept: any job that runs on this runner gets everything `LabRole` can do. I contain that with the triggers, not the credentials: fork-PR workflows need my approval for all external contributors, no self-hosted workflow triggers on `pull_request`/`pull_request_target`, and `cd.yaml` checks the triggering `workflow_run`'s event (`push`) and repository before running (`make check` enforces both).
- I can't narrow the identity anyway: `LabRole` is pre-created and I may not create IAM roles or policies, so static keys would carry the same `LabRole` permissions; they'd add exposure without reducing blast radius.

## What would show this was wrong

- A workflow run on `lab-app` that I didn't expect (check the runner's job history), or any AWS API activity from the app host that isn't the stack or CD.
- A later stage needing a job on this runner to act as a *different*, narrower identity than the host itself, which the instance profile can't give.
- Running untrusted code on the runner becomes necessary (e.g. PR previews), which would make host-wide `LabRole` access unacceptable.
