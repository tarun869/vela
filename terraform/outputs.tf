output "cluster_endpoint" {
  description = "EKS cluster API server endpoint"
  value       = module.eks.cluster_endpoint
}

output "cluster_name" {
  description = "EKS cluster name"
  value       = module.eks.cluster_name
}

output "cluster_certificate_authority_data" {
  description = "Base64-encoded certificate authority data for the cluster"
  value       = module.eks.cluster_certificate_authority_data
  sensitive   = true
}

output "kubeconfig_command" {
  description = "AWS CLI command to update kubeconfig"
  value       = "aws eks update-kubeconfig --region ${var.aws_region} --name ${module.eks.cluster_name}"
}

output "db_host" {
  description = "RDS PostgreSQL hostname"
  value       = module.rds.db_host
}

output "db_port" {
  description = "RDS PostgreSQL port"
  value       = module.rds.db_port
}

output "db_name" {
  description = "RDS database name"
  value       = module.rds.db_name
}

output "db_url_template" {
  description = "Database URL template (fill in password)"
  value       = "postgresql+asyncpg://vela:<PASSWORD>@${module.rds.db_host}:${module.rds.db_port}/${module.rds.db_name}"
  sensitive   = false
}

output "vpc_id" {
  description = "VPC ID"
  value       = module.networking.vpc_id
}

output "private_subnet_ids" {
  description = "Private subnet IDs"
  value       = module.networking.private_subnet_ids
}

output "public_subnet_ids" {
  description = "Public subnet IDs"
  value       = module.networking.public_subnet_ids
}

output "kafka_bootstrap_brokers" {
  description = "MSK Kafka bootstrap broker connection string (TLS)"
  value       = module.kafka.bootstrap_brokers_tls
}

output "kafka_bootstrap_brokers_plaintext" {
  description = "MSK Kafka bootstrap broker connection string (plaintext)"
  value       = module.kafka.bootstrap_brokers
}

output "s3_data_lake_bucket" {
  description = "S3 bucket for VPP data lake"
  value       = module.s3.data_lake_bucket
}

output "s3_reports_bucket" {
  description = "S3 bucket for reports"
  value       = module.s3.reports_bucket
}

output "s3_ml_models_bucket" {
  description = "S3 bucket for ML model artifacts"
  value       = module.s3.ml_models_bucket
}
