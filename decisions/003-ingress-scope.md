# 003: Ingress scope: campus/ISP range plus the grader

Stage: S0 · Date: 2026-11-21 · Author: akhilnathreddy · Drafted by agent: yes

## Choice

Port 80 on the app host (Traefik) is open only to my campus/ISP network range `<CIDR: fill in>` and the grader's IP from the instructor, via `ingress_cidrs` in `infra/live/terraform.tfvars` (gitignored). Nothing else on the app host is reachable from the internet; there is no port 22 anywhere.

<!-- Find the range: whois "$(curl -s https://checkip.amazonaws.com)" | grep -iE 'CIDR|inetnum' -->

## Rejected alternative

`0.0.0.0/0`: the app open to the whole internet, like a real public API.

## Why

- Open to everyone, internet scanners and bots find a public IP on port 80 within minutes. That traffic would hit `/predict` and show up in the S5 metrics and SLOs as noise I didn't generate, and it would expose any app bug to anyone. Nobody outside my network and the grader needs this app.
- A single `/32` for my own IP was the tighter option, but my address changes between campus Wi-Fi and other networks. Each change would lock me out until I edit tfvars and run `terraform apply`, which is exactly the kind of mid-lab outage I want to avoid. The campus range survives IP changes inside that network.
- Cost I accept: the range is wider than strictly needed (everyone on that network can reach the app), and I'm still locked out off-campus. From elsewhere I can check the app over SSM port forwarding, or add my current `/32` temporarily.

## What would show this was wrong

- Requests in the app's metrics or Traefik logs from addresses I can't account for inside the range.
- The grader (or I) can't reach `/version` because an address isn't in the list, e.g. the campus network uses more than one public range or changes provider.
- A later stage needs a caller outside this list (a webhook, a demo audience), which would force a decision between widening and putting auth in front.
