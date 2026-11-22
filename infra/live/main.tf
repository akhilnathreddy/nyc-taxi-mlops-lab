# S0: the root module. Three hosts (contracts/runtime.yaml), Postgres, the artifact bucket and the
# wiki secret container, all in the default VPC: Learner Lab has no NAT gateway, so hosts sit in
# public subnets and reach GHCR, GitHub and SSM over their public IPs. Inbound is only what
# security.tf allows.

locals {
  # Ports come from the frozen contract, so security groups can't drift from it.
  runtime = yamldecode(file("${path.root}/../../contracts/runtime.yaml"))
  port    = { for name, svc in local.runtime.services : name => svc.port }
}

data "aws_vpc" "default" {
  default = true
}

# One default subnet per AZ; RDS needs a subnet group spanning at least two.
data "aws_subnets" "default" {
  filter {
    name   = "vpc-id"
    values = [data.aws_vpc.default.id]
  }
  filter {
    name   = "default-for-az"
    values = ["true"]
  }
}

# All three hosts in one AZ: no cross-AZ transfer between them.
data "aws_subnet" "hosts" {
  vpc_id            = data.aws_vpc.default.id
  availability_zone = var.availability_zone
  default_for_az    = true
}

module "platform" {
  source             = "../modules/host"
  role               = "platform"
  instance_type      = var.platform_instance_type
  subnet_id          = data.aws_subnet.hosts.id
  security_group_ids = [aws_security_group.platform.id]
}

module "app" {
  source             = "../modules/host"
  role               = "app"
  instance_type      = var.app_instance_type
  subnet_id          = data.aws_subnet.hosts.id
  security_group_ids = [aws_security_group.app.id]
}

module "llm" {
  source             = "../modules/host"
  role               = "llm"
  instance_type      = var.llm_instance_type
  subnet_id          = data.aws_subnet.hosts.id
  security_group_ids = [aws_security_group.llm.id]
}

module "rds" {
  source             = "../modules/rds"
  instance_class     = var.rds_instance_class
  subnet_ids         = data.aws_subnets.default.ids
  security_group_ids = [aws_security_group.rds.id]
}

module "artifacts" {
  source = "../modules/bucket"
  name   = "lab-artifacts"
}

# Value put out of band (see the module): it never sits in state.
module "wiki_secret" {
  source      = "../modules/secret"
  name        = local.runtime.secrets.wiki.name
  description = "Wiki URL and token for the support assistant (keys: url, token)"
}

# S5: Grafana Cloud remote write for Alloy (deploy/compose.observability.yaml copies it on each host).
# Value put from the laptop, never through Terraform or GitHub.
module "grafana_secret" {
  source      = "../modules/secret"
  name        = "lab/grafana"
  description = "Grafana Cloud Prometheus remote write for Alloy (keys: url, user, token)"
}
