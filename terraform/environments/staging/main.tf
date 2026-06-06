terraform {
  required_version = ">= 1.8"
  required_providers {
    aws = { source = "hashicorp/aws", version = "~> 5.0" }
  }
  backend "s3" {
    bucket = "vela-terraform-state"
    key    = "vela/staging/terraform.tfstate"
    region = "us-west-2"
  }
}

provider "aws" {
  region = "us-west-2"
}

module "vela" {
  source = "../../"

  environment        = "staging"
  aws_region         = "us-west-2"
  vpc_cidr           = "10.20.0.0/16"
  availability_zones = ["us-west-2a", "us-west-2b", "us-west-2c"]
  kubernetes_version = "1.29"

  eks_node_groups = {
    general = {
      instance_types = ["m6i.xlarge"]
      min_size       = 3
      max_size       = 10
      desired_size   = 4
      disk_size      = 100
      labels         = { node-role = "general" }
      taints         = []
    }
    compute = {
      instance_types = ["c6i.2xlarge"]
      min_size       = 0
      max_size       = 6
      desired_size   = 1
      disk_size      = 100
      labels         = { node-role = "compute" }
      taints = [{
        key    = "compute"
        value  = "true"
        effect = "NO_SCHEDULE"
      }]
    }
  }

  rds_instance_class    = "db.m6g.large"
  rds_allocated_storage = 50
  kafka_broker_count    = 3
  kafka_broker_instance_type = "kafka.m5.large"

  tags = {
    Team      = "vela-engineering"
    CostCenter = "staging"
  }
}

output "cluster_endpoint"     { value = module.vela.cluster_endpoint }
output "db_url_template"      { value = module.vela.db_url_template }
output "kafka_bootstrap"      { value = module.vela.kafka_bootstrap_brokers }
output "s3_data_lake_bucket"  { value = module.vela.s3_data_lake_bucket }
