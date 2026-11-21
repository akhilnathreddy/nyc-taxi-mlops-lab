# 003: Ingress scope: open to everyone (0.0.0.0/0) on port 80 only

Stage: S0 · Date: 2026-11-21 · Author: akhilnathreddy · Drafted by agent: yes

## Choice

Port 80 on the app host (Traefik) is open to the whole internet: `ingress_cidrs = ["0.0.0.0/0"]` in `infra/live/terraform.tfvars` (gitignored). That is the only inbound port from the internet; there is no port 22 anywhere, MLflow, LLM and Postgres admit only other lab security groups, and Dagster stays on loopback behind SSM port forwarding.

## Rejected alternative

An allowlist: my campus/ISP range (or my own `/32`) plus the grader's `/32`.

## Why

- Reachability is the requirement for S0: the grader and I must reach `/version` and `/predict` from wherever we are. With an allowlist, every IP change (campus Wi-Fi, home, hotspot) or an address the grader didn't announce means a lockout until I edit tfvars and run `terraform apply`, an outage I cause myself.
- What I expose is small and stateless: `/predict` quotes a median, `/version` and `/healthz` reveal a commit sha. Traefik only routes the app; there is no admin UI, no Docker socket, no data store behind port 80.
- It is how the system would really run: a trip-quote API for a ride-hailing app is public by nature.
- The cost I accept: scanners and bots will find the public IP within minutes. Their requests reach `/predict` and will show up in the S5 metrics and SLOs as traffic I didn't generate, and any bug in the app is reachable by anyone. I'll have to separate that noise (by route and status in the metrics, or by looking at Traefik logs) rather than rely on the network to keep it out.

## What would show this was wrong

- Unknown traffic distorting my S5 SLOs or error budget enough that I can't tell real regressions from scanner noise.
- Load from outside (scans, floods) making the app host slow or the `/predict` latency SLO fail.
- A later stage puts something sensitive behind port 80 (the S7 assistant, anything with data or a token). That would force a choice between narrowing ingress and putting authentication in front.
