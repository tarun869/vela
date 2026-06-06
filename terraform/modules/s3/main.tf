locals {
  buckets = {
    data_lake  = "${var.prefix}-data-lake-${var.environment}"
    reports    = "${var.prefix}-reports-${var.environment}"
    ml_models  = "${var.prefix}-ml-models-${var.environment}"
    backups    = "${var.prefix}-backups-${var.environment}"
    terraform  = "${var.prefix}-terraform-state"
  }
}

resource "aws_kms_key" "s3" {
  description             = "KMS key for Vela S3 buckets (${var.environment})"
  deletion_window_in_days = 7
  enable_key_rotation     = true
  tags                    = var.tags
}

resource "aws_s3_bucket" "buckets" {
  for_each = local.buckets
  bucket   = each.value
  tags     = merge(var.tags, { Purpose = each.key })
}

resource "aws_s3_bucket_versioning" "buckets" {
  for_each = local.buckets
  bucket   = aws_s3_bucket.buckets[each.key].id
  versioning_configuration {
    status = "Enabled"
  }
}

resource "aws_s3_bucket_server_side_encryption_configuration" "buckets" {
  for_each = local.buckets
  bucket   = aws_s3_bucket.buckets[each.key].id
  rule {
    apply_server_side_encryption_by_default {
      sse_algorithm     = "aws:kms"
      kms_master_key_id = aws_kms_key.s3.arn
    }
    bucket_key_enabled = true
  }
}

resource "aws_s3_bucket_public_access_block" "buckets" {
  for_each = local.buckets
  bucket   = aws_s3_bucket.buckets[each.key].id

  block_public_acls       = true
  block_public_policy     = true
  ignore_public_acls      = true
  restrict_public_buckets = true
}

# Lifecycle rules for data lake
resource "aws_s3_bucket_lifecycle_configuration" "data_lake" {
  bucket = aws_s3_bucket.buckets["data_lake"].id

  rule {
    id     = "telemetry-archive"
    status = "Enabled"

    filter {
      prefix = "telemetry/"
    }

    transition {
      days          = 30
      storage_class = "STANDARD_IA"
    }

    transition {
      days          = 90
      storage_class = "GLACIER_IR"
    }

    expiration {
      days = 365
    }
  }

  rule {
    id     = "dispatch-archive"
    status = "Enabled"

    filter {
      prefix = "dispatch/"
    }

    transition {
      days          = 90
      storage_class = "STANDARD_IA"
    }

    transition {
      days          = 365
      storage_class = "GLACIER"
    }
  }
}

output "data_lake_bucket" {
  value = aws_s3_bucket.buckets["data_lake"].id
}

output "reports_bucket" {
  value = aws_s3_bucket.buckets["reports"].id
}

output "ml_models_bucket" {
  value = aws_s3_bucket.buckets["ml_models"].id
}

output "backups_bucket" {
  value = aws_s3_bucket.buckets["backups"].id
}
