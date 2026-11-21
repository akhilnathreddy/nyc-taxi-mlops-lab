# 003: Ingress scope: my IP and the grader's IP only

Stage: S0 · Date: 2026-11-21 · Author: akhilnathreddy · Drafted by agent: yes

## Choice

Port 80 on the app host (Traefik) is open to exactly two addresses: my laptop's public IP and the grader's IP from the instructor, `ingress_cidrs = ["<my IP>/32", "<grader IP>/32"]` in `infra/live/terraform.tfvars` (gitignored, so neither address is in the public repo). Nothing else on the app host is reachable from the internet; there is no port 22 anywhere, and the other services admit only lab security groups.

## Rejected alternative

`0.0.0.0/0`: the app open to the whole internet, reachable from any network without maintenance.

## Why

- Only two parties need this app: me and the grader. Opening it to everyone buys reachability nobody needs and costs a lot: scanners and bots find a public IP on port 80 within minutes, their requests hit `/predict`, and they would show up in my S5 metrics and SLOs as traffic I didn't generate, making real regressions harder to see.
- Every bug in the app would be reachable by anyone. With two `/32`s the exposed surface is effectively zero.
- The cost I accept: when my public IP changes (another Wi-Fi, a hotspot, my ISP reassigning it) I'm locked out until I update `ingress_cidrs` and run `terraform apply`, which only touches the security-group rules (seconds, no host replacement). In the meantime I can still reach the app through SSM port forwarding. The grader's IP has to be correct and in place before grading.

## What would show this was wrong

- I'm locked out often enough that updating my IP becomes a regular chore (more than about once per lab day).
- The grader can't reach `/version` or `/predict` because their address differs from the one I was given, or they use more than one.
- A later stage needs a caller I can't list by IP (a webhook, a demo audience, a teammate on another network), which would force a choice between widening ingress and putting authentication in front.
