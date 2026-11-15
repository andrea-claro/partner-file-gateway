# AWS Transfer Family: the managed service that SFTPGo stands in for locally.
# Validated in CI, never applied by this project.

locals {
  tags = merge(var.tags, { Component = "transfer" })
}

data "aws_caller_identity" "current" {}

resource "aws_cloudwatch_log_group" "transfer" {
  name              = "/aws/transfer/${var.name}"
  retention_in_days = var.log_retention_days
  kms_key_id        = var.kms_key_arn
  tags              = local.tags
}

resource "aws_transfer_server" "sftp" {
  #checkov:skip=CKV_AWS_164:Partners connect from the internet. In production, put the endpoint in a VPC with Elastic IPs and security groups allow-listing partner networks.
  protocols              = ["SFTP"]
  identity_provider_type = "SERVICE_MANAGED"
  endpoint_type          = "PUBLIC"
  domain                 = "S3"
  security_policy_name   = var.security_policy_name

  structured_log_destinations = ["${aws_cloudwatch_log_group.transfer.arn}:*"]

  tags = merge(local.tags, { Name = var.name })
}

# --- One role per partner, scoped to its own prefix ---------------------------------

data "aws_iam_policy_document" "partner_assume" {
  statement {
    actions = ["sts:AssumeRole"]

    principals {
      type        = "Service"
      identifiers = ["transfer.amazonaws.com"]
    }

    condition {
      test     = "StringEquals"
      variable = "aws:SourceAccount"
      values   = [data.aws_caller_identity.current.account_id]
    }

    condition {
      test     = "ArnLike"
      variable = "aws:SourceArn"
      values   = ["${aws_transfer_server.sftp.arn}*"]
    }
  }
}

resource "aws_iam_role" "partner" {
  for_each = var.partners

  name               = "${var.name}-partner-${each.key}"
  assume_role_policy = data.aws_iam_policy_document.partner_assume.json
  tags               = local.tags
}

data "aws_iam_policy_document" "partner" {
  for_each = var.partners

  statement {
    sid       = "ListOwnPrefix"
    actions   = ["s3:ListBucket"]
    resources = [var.bucket_arn]

    condition {
      test     = "StringLike"
      variable = "s3:prefix"
      values   = ["inbound/${each.key}/", "inbound/${each.key}/*"]
    }
  }

  statement {
    sid       = "UploadToOwnPrefix"
    actions   = ["s3:PutObject"]
    resources = ["${var.bucket_arn}/inbound/${each.key}/*"]
  }

  dynamic "statement" {
    for_each = var.kms_key_arn == null ? [] : [1]
    content {
      sid       = "EncryptUploads"
      actions   = ["kms:GenerateDataKey", "kms:Decrypt"]
      resources = [var.kms_key_arn]
    }
  }
}

resource "aws_iam_role_policy" "partner" {
  for_each = var.partners

  name   = "own-prefix-upload-only"
  role   = aws_iam_role.partner[each.key].id
  policy = data.aws_iam_policy_document.partner[each.key].json
}

resource "aws_transfer_user" "partner" {
  for_each = var.partners

  server_id           = aws_transfer_server.sftp.id
  user_name           = each.key
  role                = aws_iam_role.partner[each.key].arn
  home_directory_type = "LOGICAL"

  # The partner sees "/" and lands in inbound/<partner>/ (same jail as SFTPGo).
  home_directory_mappings {
    entry  = "/"
    target = "/${var.bucket_name}/inbound/${each.key}"
  }

  tags = local.tags
}

resource "aws_transfer_ssh_key" "partner" {
  for_each = var.partners

  server_id = aws_transfer_server.sftp.id
  user_name = aws_transfer_user.partner[each.key].user_name
  body      = each.value
}
