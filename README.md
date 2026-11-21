# NYC taxi trip-duration: from stub to production-shaped ML system

A ride-hailing app quotes trip times with a static median. Product wants predicted durations, plus a support assistant that explains them. Over two days you build the data, model and deploy pipelines, then operate and extend them.

## Current state

| Stage | What it delivers | Status |
| --- | --- | --- |
| [S0](stages/S0.md) walking skeleton | A push to `main` is tested, built as a `linux/arm64` image on GHCR and deployed to the app host; `/predict` quotes the static median (12.25 min) | ✅ done |
| [S1](stages/S1.md) data pipeline | A month's trip file landing in the data bucket ends up in Redshift and in the `zone_hour_stats` mart with no one pressing a button; schema drift and bad months never reach the mart | ✅ done (2024-01 to 2024-04 loaded) |
| S2 onward | Model, serving, operations, assistant | not started: each handout arrives with its `stage-N` tag |

## Architecture

```
 GitHub (public repo)                              AWS us-east-1, Learner Lab, default VPC (no NAT, no SSH)
 ─────────────────────                             ──────────────────────────────────────────────────────────
 push to main
   ├─ ci.yaml        make check; arm64 app image ──► GHCR
   │     └─ success ─► cd.yaml ─────[runner lab-app]──► app host (t4g.large, Elastic IP)
   │                                                     Traefik :80 ──► app  (/version, /predict, /healthz)
   └─ platform.yaml  (pipelines/**, contracts/**)
         test, pipelines image ──► GHCR
         deploy ────────────────[runner lab-platform]─► platform host (t4g.large)
                                                         Dagster webserver (loopback :3000), daemon, code
                                                         MLflow :5000 (app host only)
                                                              │ run storage        │ Data API as labadmin
                                                              ▼                    ▼
                                                         RDS Postgres         Redshift ra3.large "lab"
                                                                                   ▲ COPY (iam_role default = LabRole)
 instructor data bucket  trips/yellow_tripdata_YYYY-MM.parquet ──trip_files_sensor──┘
                                                         llm host (m8g.large): idle until S6
```

Hosts authenticate to AWS with `LabInstanceProfile` (`LabRole`); nothing in GitHub holds AWS credentials. Port 80 on the app host is the only inbound port from the internet ([decision 003](decisions/003-ingress-scope.md)); every other service admits only lab security groups.

### The data pipeline (S1)

```
trips/ in the bucket ──sensor──► trip_files[month] ──schema_contract (blocks)──► raw_trips[month]   COPY, idempotent
                                                                                        │
                                  stg_trips[month] ◄─────────────────────────────────────┘
                                        │ 5 blocking + 6 warning quality checks
                                        ▼
                                  zone_hour_stats ◄── taxi_zones
```

- **Sensor** `trip_files_sensor`: every 60 s, lists `trips/`; a new file adds its month as a partition and starts `ingest_month`; a replaced file (new ETag) runs again; an unchanged one never does.
- **Schema gate** `schema_contract`: compares the Parquet footer with [contracts/trips.schema.yaml](contracts/trips.schema.yaml) (count, order, case-insensitive names, exact types) before anything is copied.
- **Load** `raw_trips`: COPY into a temp table, then delete and insert the month in one transaction, so a rerun replaces a month and a failed COPY keeps the old one ([decision 004](decisions/004-copy-vs-spectrum.md)).
- **Quality** on `stg_trips`: integrity failures block the mart; anomalies warn. Every threshold comes from the measured 2024-01..04 data ([decision 006](decisions/006-blocking-vs-warning.md)).

## Decisions

| # | Decision | Choice |
| --- | --- | --- |
| [001](decisions/001-runner-credentials.md) | Runner credentials | The host's instance profile, no static keys in GitHub |
| [002](decisions/002-image-tag-scheme.md) | Image tag scheme | `sha-<short sha>`; a rollback points at an earlier sha tag |
| [003](decisions/003-ingress-scope.md) | Ingress scope | Port 80 open to `0.0.0.0/0`, nothing else from the internet |
| [004](decisions/004-copy-vs-spectrum.md) | COPY vs Spectrum | COPY each month into Redshift |
| [005](decisions/005-dist-and-sort-keys.md) | Dist and sort keys | `raw_trips` AUTO / `source_file`; `stg_trips` AUTO / `pickup_at`; `taxi_zones` ALL |
| [006](decisions/006-blocking-vs-warning.md) | Blocking vs warning | Integrity checks block, anomalies warn, thresholds from 2024-01..04 |

## Operating it

**AWS credentials** (every Start Lab): Learner Lab → AWS Details → AWS CLI → Show, and replace the *whole* content of `~/.aws/credentials` with that block. Two `[default]` sections make the CLI refuse the file. Never put credentials in this folder: the repo is public.

```bash
scripts/health.sh                                                   # one line per piece of the lab; start here
curl "http://$(terraform -chdir=infra/live output -raw app_public_ip)/version"   # git_sha of the deployed commit

# Dagster UI (once: brew install --cask session-manager-plugin), then http://localhost:3000
aws ssm start-session --target "$(terraform -chdir=infra/live output -raw platform_instance_id)" \
  --document-name AWS-StartPortForwardingSession --parameters portNumber=3000,localPortNumber=3000

scripts/dagster-run.sh ingest_month --partition 2024-03 --wait      # reload one month (idempotent)

aws redshift pause-cluster  --cluster-identifier lab                # end of day: storage-only billing
aws redshift resume-cluster --cluster-identifier lab                # ~3 min; Dagster runs fail until it's back
```

After Start Lab the hosts restart and everything comes back by itself at the same addresses (Elastic IPs): the app, both runners, Dagster and its sensor. `health.sh` warns that your laptop IP is not in `ingress_cidrs` when ingress is `0.0.0.0/0`; that warning is a false alarm.

Pass `-R <owner>/nyc-taxi-mlops-lab` to `gh variable` and `gh secret`: with an `upstream` remote they can resolve to the template repo instead of yours.

**Checks:** `make check` (what CI and the grader run), `make test-pipelines` (fake Redshift and S3, no AWS), `make agent-check`.

## Get started (before Day 1, 10:30)

1. **Your own copy**, public (GitHub's approval gates, which you need from S3, only work on public repos):

   ```bash
   gh repo create <your-github-user>/nyc-taxi-mlops-lab --public --template balwa/nyc-taxi-mlops-lab --clone
   cd nyc-taxi-mlops-lab && git remote add upstream https://github.com/balwa/nyc-taxi-mlops-lab.git
   ```

2. **Tools on your laptop** (macOS or Linux; on Windows, work inside WSL): `git`, `gh` (logged in), the AWS CLI v2, Terraform 1.11 or later, `uv`, `make`, `jq`, Docker (optional, for the observability checks) and Claude Code.
3. **Check:** `make check` passes, and `make agent-check` shows that Claude Code loads `AGENTS.md` here and in `infra/` and `pipelines/`. Each `CLAUDE.md` is a link to its `AGENTS.md`: keep it that way. If you run `/init` or edit a `CLAUDE.md`, run `make agent-check` again.

## Where things are

- What to do now: [stages/](stages/), one handout per stage
- Rules for your coding agent: [AGENTS.md](AGENTS.md)
- Frozen interfaces: [contracts/](contracts/)
- Infrastructure: [infra/](infra/); host stacks: [deploy/](deploy/); the Dagster project: [pipelines/](pipelines/)
- Your decision records: [decisions/](decisions/); your runbooks (from S4): [runbooks/](runbooks/)
- `make check` runs the same static checks as the grader (needs `uv`, `terraform`, `make`; with Docker running it also checks the observability rules and Alloy configs, which CI always does).
- What state everything is in: `scripts/health.sh`.

Falling behind is planned for: `git fetch upstream --tags`, put `stage-N` on your `main`, then `scripts/catch-up.sh N`. `stage-N` means "ready to start SN". It replaces your `main` with the reference, decision records included, so it's a last resort once you have work of your own.
