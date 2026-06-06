terraform {
  required_version = ">= 1.8"
  required_providers {
    aws = { source = "hashicorp/aws", version = "~> 5.0" }
  }
  backend "s3" {
    bucket  = "vela-terraform-state"
    key     = "vela/prod/terraform.tfstate"
    region  = "us-west-2"
    encrypt = true
    # State locking via DynamoDB
    dynamodb_table = "vela-terraform-locks"
  }
}

provider "aws" {
  region = "us-west-2"
  default_tags {
    tags = {
      Environment = "prod"
      Project     = "vela-vpp"
      ManagedBy   = "terraform"
    }
  }
}

module "vela" {
  source = "../../"

  environment        = "prod"
  aws_region         = "us-west-2"
  vpc_cidr           = "10.0.0.0/16"
  availability_zones = ["us-west-2a", "us-west-2b", "us-west-2c"]
  kubernetes_version = "1.29"

  eks_node_groups = {
    general = {
      instance_types = ["m6i.2xlarge"]
      min_size       = 6
      max_size       = 30
      desired_size   = 9
      disk_size      = 100
      labels         = { node-role = "general" }
      taints         = []
    }
    compute = {
      instance_types = ["c6i.4xlarge"]
      min_size       = 2
      max_size       = 20
      desired_size   = 4
      disk_size      = 100
      labels         = { node-role = "compute" }
      taints = [{
        key    = "compute"
        value  = "true"
        effect = "NO_SCHEDULE"
      }]
    }
    ml_training = {
      instance_types = ["r6i.8xlarge"]
      min_size       = 0
      max_size       = 4
      desired_size   = 0
      disk_size      = 500
      labels         = { node-role = "ml-training" }
      taints = [{
        key    = "ml-training"
        value  = "true"
        effect = "NO_SCHEDULE"
      }]
    }
  }

  rds_instance_class    = "db.r6g.4xlarge"
  rds_allocated_storage = 500
  kafka_broker_count    = 3
  kafka_broker_instance_type = "kafka.m5.4xlarge"

  tags = {
    Team      = "vela-engineering"
    CostCenter = "prod"
    Compliance = "sox"
  }
}

output "cluster_endpoint"               { value = module.vela.cluster_endpoint }
output "cluster_name"                   { value = module.vela.cluster_name }
output "db_url_template"                { value = module.vela.db_url_template }
output "kafka_bootstrap_brokers_tls"    { value = module.vela.kafka_bootstrap_brokers }
output "s3_data_lake_bucket"            { value = module.vela.s3_data_lake_bucket }
output "s3_reports_bucket"              { value = module.vela.s3_reports_bucket }
output "s3_ml_models_bucket"            { value = module.vela.s3_ml_models_bucket }
output "kubeconfig_command"             { value = module.vela.kubeconfig_command }
