terraform {
  required_version = ">= 1.8"
  required_providers {
    aws = { source = "hashicorp/aws", version = "~> 5.0" }
  }
  backend "s3" {
    bucket = "vela-terraform-state"
    key    = "vela/dev/terraform.tfstate"
    region = "us-west-2"
  }
}

provider "aws" {
  region = "us-west-2"
}

module "vela" {
  source = "../../"

  environment        = "dev"
  aws_region         = "us-west-2"
  vpc_cidr           = "10.10.0.0/16"
  availability_zones = ["us-west-2a", "us-west-2b"]
  kubernetes_version = "1.29"

  eks_node_groups = {
    general = {
      instance_types = ["m6i.large"]
      min_size       = 2
      max_size       = 6
      desired_size   = 3
      disk_size      = 50
      labels         = { node-role = "general" }
      taints         = []
    }
  }

  rds_instance_class    = "db.t4g.medium"
  rds_allocated_storage = 20
  kafka_broker_count    = 1
  kafka_broker_instance_type = "kafka.t3.small"

  tags = {
    Team      = "vela-engineering"
    CostCenter = "dev"
  }
}

output "cluster_endpoint" { value = module.vela.cluster_endpoint }
output "db_url_template"  { value = module.vela.db_url_template }
