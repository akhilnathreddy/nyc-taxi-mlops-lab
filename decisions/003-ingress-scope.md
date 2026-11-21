# 003: Ingress scope: open to everyone (0.0.0.0/0) on port 80 only

Stage: S0 · Date: 2026-11-21 · Author: akhilnathreddy · Drafted by agent: yes

## Choice

Port 80 on the app host (Traefik) is open to the whole internet: `ingress_cidrs = ["0.0.0.0/0"]` in `infra/live/terraform.tfvars` (gitignored). That is the only inbound port from the internet; there is no port 22 anywhere, MLflow, LLM and Postgres admit only other lab security groups, and Dagster stays on loopback behind SSM port forwarding.

## Rejected alternative

An allowlist of `/32`s: my laptop's public IP plus the grader's IP from the instructor. (I also considered my campus/ISP range plus the grader.)

## Why

- Reachability is what S0 is graded on: the grader and I must reach `/version` and `/predict` from wherever we are. An allowlist depends on knowing the grader's exact address in advance, and locks me out every time my own IP changes (campus Wi-Fi, home, hotspot) until I edit tfvars and run `terraform apply`. Those are outages I would cause myself, in a lab where time is the scarcest resource.
- What I expose is small and stateless: `/predict` quotes a median, `/version` and `/healthz` reveal a commit sha. Traefik only routes the app; there is no admin UI, no Docker socket and no data store behind port 80.
- It matches how the system would really run: a trip-quote API for a ride-hailing app is public by nature.
- The cost I accept: scanners and bots will find the public IP within minutes. Their requests reach `/predict` and will show up in the S5 metrics and SLOs as traffic I didn't generate, and any bug in the app is reachable by anyone. I'll have to separate that noise (by route and status in the metrics, or in Traefik's logs) rather than rely on the network to keep it out.

## What would show this was wrong

- Unknown traffic distorting my S5 SLOs or error budget enough that I can't tell real regressions from scanner noise.
- Load from outside (scans, floods) slowing the app host or failing the `/predict` latency SLO.
- A later stage puts something sensitive behind port 80 (the S7 assistant, anything with data or a token). That forces a choice between narrowing ingress back to an allowlist and putting authentication in front.
