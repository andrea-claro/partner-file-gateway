# Transfer bucket: partners write to inbound/<partner>/, the pipeline moves files
# to processed/ or quarantine/. Private, versioned, encrypted, TLS-only, and
# every Object Created event goes to EventBridge.

resource "aws_s3_bucket" "transfer" {
  #checkov:skip=CKV_AWS_18:Server access logs need a separate log bucket; the per-file audit trail lives in DynamoDB. Enable with CloudTrail data events on real AWS.
  #checkov:skip=CKV_AWS_144:Single-region demo; cross-region replication is out of scope.
  #checkov:skip=CKV_AWS_145:SSE-KMS is supported through var.kms_key_arn (used by envs/aws); LocalStack uses SSE-S3.
  bucket        = var.bucket_name
  force_destroy = var.force_destroy
  tags          = merge(var.tags, { Component = "storage" })
}

resource "aws_s3_bucket_ownership_controls" "transfer" {
  bucket = aws_s3_bucket.transfer.id

  rule {
    object_ownership = "BucketOwnerEnforced"
  }
}

resource "aws_s3_bucket_public_access_block" "transfer" {
  bucket                  = aws_s3_bucket.transfer.id
  block_public_acls       = true
  block_public_policy     = true
  ignore_public_acls      = true
  restrict_public_buckets = true
}

resource "aws_s3_bucket_versioning" "transfer" {
  bucket = aws_s3_bucket.transfer.id

  versioning_configuration {
    status = "Enabled"
  }
}

resource "aws_s3_bucket_server_side_encryption_configuration" "transfer" {
  bucket = aws_s3_bucket.transfer.id

  rule {
    apply_server_side_encryption_by_default {
      sse_algorithm     = var.kms_key_arn == null ? "AES256" : "aws:kms"
      kms_master_key_id = var.kms_key_arn
    }
    bucket_key_enabled = var.kms_key_arn != null
  }
}

resource "aws_s3_bucket_lifecycle_configuration" "transfer" {
  bucket = aws_s3_bucket.transfer.id

  rule {
    id     = "abort-incomplete-multipart-uploads"
    status = "Enabled"
    filter {}

    abort_incomplete_multipart_upload {
      days_after_initiation = 1
    }
  }

  rule {
    id     = "expire-noncurrent-versions"
    status = "Enabled"
    filter {}

    noncurrent_version_expiration {
      noncurrent_days = var.noncurrent_version_retention_days
    }
  }

  rule {
    id     = "expire-quarantine"
    status = "Enabled"

    filter {
      prefix = "quarantine/"
    }

    expiration {
      days = var.quarantine_retention_days
    }
  }

  depends_on = [aws_s3_bucket_versioning.transfer]
}

data "aws_iam_policy_document" "transfer" {
  statement {
    sid       = "DenyInsecureTransport"
    effect    = "Deny"
    actions   = ["s3:*"]
    resources = [aws_s3_bucket.transfer.arn, "${aws_s3_bucket.transfer.arn}/*"]

    principals {
      type        = "*"
      identifiers = ["*"]
    }

    condition {
      test     = "Bool"
      variable = "aws:SecureTransport"
      values   = ["false"]
    }
  }
}

resource "aws_s3_bucket_policy" "transfer" {
  bucket = aws_s3_bucket.transfer.id
  policy = data.aws_iam_policy_document.transfer.json

  depends_on = [aws_s3_bucket_public_access_block.transfer]
}

# Same pattern as on real AWS: S3 -> EventBridge -> Step Functions (ADR-002).
resource "aws_s3_bucket_notification" "transfer" {
  bucket      = aws_s3_bucket.transfer.id
  eventbridge = true
}
