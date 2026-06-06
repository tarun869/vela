# Root Terraform module — calls submodules for all Vela infrastructure

module "networking" {
  source = "./modules/networking"

  environment        = var.environment
  vpc_cidr           = var.vpc_cidr
  availability_zones = var.availability_zones
  tags               = local.common_tags
}

module "eks" {
  source = "./modules/eks"

  environment        = var.environment
  cluster_name       = local.cluster_name
  kubernetes_version = var.kubernetes_version
  vpc_id             = module.networking.vpc_id
  private_subnet_ids = module.networking.private_subnet_ids
  node_groups        = var.eks_node_groups
  tags               = local.common_tags

  depends_on = [module.networking]
}

module "rds" {
  source = "./modules/rds"

  environment         = var.environment
  identifier          = "vela-${var.environment}"
  vpc_id              = module.networking.vpc_id
  subnet_ids          = module.networking.private_subnet_ids
  allowed_cidr_blocks = [var.vpc_cidr]
  instance_class      = var.rds_instance_class
  allocated_storage   = var.rds_allocated_storage
  db_name             = "vela"
  tags                = local.common_tags

  depends_on = [module.networking]
}

module "s3" {
  source = "./modules/s3"

  environment = var.environment
  prefix      = "vela"
  tags        = local.common_tags
}

module "kafka" {
  source = "./modules/kafka"

  environment        = var.environment
  cluster_name       = "vela-${var.environment}"
  vpc_id             = module.networking.vpc_id
  subnet_ids         = module.networking.private_subnet_ids
  allowed_cidr_blocks = [var.vpc_cidr]
  broker_count       = var.kafka_broker_count
  broker_instance_type = var.kafka_broker_instance_type
  tags               = local.common_tags

  depends_on = [module.networking]
}

locals {
  cluster_name = "vela-${var.environment}"
  common_tags = merge(var.tags, {
    Environment = var.environment
    Project     = "vela-vpp"
    ManagedBy   = "terraform"
  })
}
