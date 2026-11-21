# S1: the Redshift cluster (infra/modules/redshift) and the outputs that contracts/platform.yaml lists
# under terraform_outputs. No ingress rule: clients use the Data API, which never connects to the
# cluster's port.

module "warehouse" {
  source     = "../modules/redshift"
  name       = local.platform.warehouse.cluster_id
  database   = local.platform.warehouse.database
  admin_user = local.platform.warehouse.users.pipeline
  subnet_ids = data.aws_subnets.default.ids
}

locals {
  platform = yamldecode(file("${path.root}/../../contracts/platform.yaml"))
}

output "redshift_cluster_id" {
  value = module.warehouse.cluster_id
}

output "redshift_database" {
  value = module.warehouse.database
}
