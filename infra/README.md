# infra/

Given: `modules/` (host, rds, bucket, secret, redshift, notebook), `live/versions.tf` and `variables.tf`, `bootstrap/state-bucket.sh`.
S0 builds: `live/main.tf` (wiring), `live/security.tf` (security groups), `live/outputs.tf` (names from `contracts/runtime.yaml`).
S1 builds: `live/warehouse.tf` (the Redshift cluster and the outputs `contracts/platform.yaml` lists).
S5 and S6 add secret containers `lab/grafana` and `lab/langfuse` in `live/main.tf`; their values are put from a laptop with `aws secretsmanager put-secret-value`, so they never sit in Terraform state.
Decisions: [runner credentials](../decisions/001-runner-credentials.md); [ingress scope](../decisions/003-ingress-scope.md).

```bash
infra/bootstrap/state-bucket.sh                                       # once per account; writes live/backend.hcl
cp infra/live/terraform.tfvars.example infra/live/terraform.tfvars   # then set ingress_cidrs (decision 003)
terraform -chdir=infra/live init -backend-config=backend.hcl
terraform -chdir=infra/live plan -out=tfplan                          # review, then: apply tfplan
```

## What `live/` creates

| File | Resources | Notes |
| --- | --- | --- |
| `main.tf` | Hosts `platform`, `app` (t4g.large) and `llm` (m8g.large) with Elastic IPs; RDS Postgres (db.t4g.medium, gp2, private); the artifact bucket; the secret containers `lab/wiki`, `lab/grafana` (S5) and `lab/langfuse` (S6) | All hosts in one AZ of the default VPC; ports come from `contracts/runtime.yaml` |
| `security.tf` | One security group per host plus RDS | Internet reaches only port 80 on the app host (`var.ingress_cidrs`); hosts admit each other by group, never by IP (the app and platform hosts reach the LLM host's chat and embedding ports); no port 22 anywhere |
| `warehouse.tf` | Redshift `lab` (ra3.large, single node, encrypted, private) | Names come from `contracts/platform.yaml`; no ingress (clients use the Data API); `LabRole` is the default role, so COPY says `iam_role default` |
| `outputs.tf` | `app_public_ip`, `*_instance_id`, `*_private_ip`, `rds_endpoint`, `artifact_bucket` | Read by `scripts/` and the grader; `warehouse.tf` adds `redshift_cluster_id`, `redshift_database` |

State is in S3 (`lab-tfstate-<account>`, versioned, public access blocked) with S3's native lock file. `backend.hcl`, `terraform.tfvars`, plans and state are gitignored: they name your account or your IP.

Every resource carries the provider's default tag `project = mlops-lab`; teardown finds resources by it (Tag Editor in the console lists them all).
