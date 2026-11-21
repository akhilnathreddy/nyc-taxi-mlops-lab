# S0: security groups and rules. One group per host role plus RDS; hosts admit each other by group,
# never by IP, so a replaced host keeps its access.
#
# Decision point: who may reach the app (ingress scope)? That's var.ingress_cidrs, set in
# terraform.tfvars. Record it in decisions/.
# There is no SSH in this lab: no port 22 anywhere. Shell is SSM Session Manager; Dagster (3000)
# stays on loopback and is reached with SSM port forwarding.

resource "aws_security_group" "app" {
  name_prefix = "lab-app-"
  vpc_id      = data.aws_vpc.default.id
  description = "App host: Traefik on port 80 from ingress_cidrs only"
  tags        = { Name = "lab-app" }

  lifecycle {
    create_before_destroy = true
  }
}

resource "aws_security_group" "platform" {
  name_prefix = "lab-platform-"
  vpc_id      = data.aws_vpc.default.id
  description = "Platform host: MLflow from the app host"
  tags        = { Name = "lab-platform" }

  lifecycle {
    create_before_destroy = true
  }
}

resource "aws_security_group" "llm" {
  name_prefix = "lab-llm-"
  vpc_id      = data.aws_vpc.default.id
  description = "LLM host: chat and embeddings from the app and platform hosts"
  tags        = { Name = "lab-llm" }

  lifecycle {
    create_before_destroy = true
  }
}

resource "aws_security_group" "rds" {
  name_prefix = "lab-rds-"
  vpc_id      = data.aws_vpc.default.id
  description = "RDS: Postgres from the app and platform hosts"
  tags        = { Name = "lab-rds" }

  lifecycle {
    create_before_destroy = true
  }
}

# Hosts need outbound for dnf, GHCR, GitHub (the runner), SSM and the data bucket.
resource "aws_vpc_security_group_egress_rule" "all" {
  for_each          = { app = aws_security_group.app.id, platform = aws_security_group.platform.id, llm = aws_security_group.llm.id }
  security_group_id = each.value
  description       = "All outbound"
  ip_protocol       = "-1"
  cidr_ipv4         = "0.0.0.0/0"
}

# Internet -> app: Traefik.
resource "aws_vpc_security_group_ingress_rule" "app_http" {
  for_each          = toset(var.ingress_cidrs)
  security_group_id = aws_security_group.app.id
  description       = "Traefik"
  ip_protocol       = "tcp"
  from_port         = local.port.traefik
  to_port           = local.port.traefik
  cidr_ipv4         = each.value
}

# app -> platform: MLflow.
resource "aws_vpc_security_group_ingress_rule" "platform_mlflow" {
  security_group_id            = aws_security_group.platform.id
  description                  = "MLflow from the app host"
  ip_protocol                  = "tcp"
  from_port                    = local.port.mlflow
  to_port                      = local.port.mlflow
  referenced_security_group_id = aws_security_group.app.id
}

# app, platform -> llm: chat and embeddings.
locals {
  llm_ingress = {
    for pair in setproduct(["llm-chat", "llm-embed"], ["app", "platform"]) :
    "${pair[0]}-from-${pair[1]}" => { service = pair[0], source = pair[1] }
  }
  host_sg = { app = aws_security_group.app.id, platform = aws_security_group.platform.id }
}

resource "aws_vpc_security_group_ingress_rule" "llm" {
  for_each                     = local.llm_ingress
  security_group_id            = aws_security_group.llm.id
  description                  = "${each.value.service} from the ${each.value.source} host"
  ip_protocol                  = "tcp"
  from_port                    = local.port[each.value.service]
  to_port                      = local.port[each.value.service]
  referenced_security_group_id = local.host_sg[each.value.source]
}

# app, platform -> rds: Postgres.
resource "aws_vpc_security_group_ingress_rule" "rds" {
  for_each                     = local.host_sg
  security_group_id            = aws_security_group.rds.id
  description                  = "Postgres from the ${each.key} host"
  ip_protocol                  = "tcp"
  from_port                    = 5432
  to_port                      = 5432
  referenced_security_group_id = each.value
}
