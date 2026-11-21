# S2: wire infra/modules/notebook (the SageMaker notebook) into this root module, let it reach MLflow
# on the platform host (port 5000, runtime.yaml), and output its name as notebook_name.
# Set github_repo in terraform.tfvars: the notebook clones your public repo.

module "notebook" {
  source    = "../modules/notebook"
  subnet_id = data.aws_subnet.hosts.id
  repo_url  = "https://github.com/${var.github_repo}.git"
  env = {
    MLFLOW_TRACKING_URI = "http://${module.platform.private_ip}:${local.port.mlflow}"
    REDSHIFT_CLUSTER_ID = module.warehouse.cluster_id
    REDSHIFT_DATABASE   = module.warehouse.database
    REDSHIFT_DB_USER    = local.platform.warehouse.users.pipeline
  }
}

# notebook -> platform: MLflow.
resource "aws_vpc_security_group_ingress_rule" "platform_mlflow_notebook" {
  security_group_id            = aws_security_group.platform.id
  description                  = "MLflow from the notebook"
  ip_protocol                  = "tcp"
  from_port                    = local.port.mlflow
  to_port                      = local.port.mlflow
  referenced_security_group_id = module.notebook.security_group_id
}

output "notebook_name" {
  value = module.notebook.name
}
