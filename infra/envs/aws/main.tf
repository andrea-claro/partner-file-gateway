# Real-AWS target, validated in CI and never applied. Same modules as
# infra/envs/local (ADR-005), plus Transfer Family and a customer managed key.

locals {
  tags = {
    Project     = "partner-file-gateway"
    Environment = "aws"
    ManagedBy   = "terraform"
  }
  repo_root = "${path.module}/../../.."
}

data "aws_caller_identity" "current" {}
data "aws_region" "current" {}

data "aws_iam_policy_document" "kms" {
  #checkov:skip=CKV_AWS_109:Key policy: Resource "*" means this key only; administration stays with the account root.
  #checkov:skip=CKV_AWS_111:Key policy: Resource "*" means this key only; service statements are scoped by conditions.
  #checkov:skip=CKV_AWS_356:Key policy: Resource "*" is the required form inside a KMS key policy.
  statement {
    sid       = "AccountAdministration"
    actions   = ["kms:*"]
    resources = ["*"] # in a key policy, "*" means "this key"

    principals {
      type        = "AWS"
      identifiers = ["arn:aws:iam::${data.aws_caller_identity.current.account_id}:root"]
    }
  }

  statement {
    sid       = "CloudWatchLogs"
    actions   = ["kms:Encrypt", "kms:Decrypt", "kms:ReEncrypt*", "kms:GenerateDataKey*", "kms:DescribeKey"]
    resources = ["*"]

    principals {
      type        = "Service"
      identifiers = ["logs.${data.aws_region.current.region}.amazonaws.com"]
    }

    condition {
      test     = "ArnLike"
      variable = "kms:EncryptionContext:aws:logs:arn"
      values   = ["arn:aws:logs:${data.aws_region.current.region}:${data.aws_caller_identity.current.account_id}:log-group:*"]
    }
  }

  statement {
    sid       = "EventBridgeToEncryptedQueues"
    actions   = ["kms:Decrypt", "kms:GenerateDataKey"]
    resources = ["*"]

    principals {
      type        = "Service"
      identifiers = ["events.amazonaws.com"]
    }

    condition {
      test     = "StringEquals"
      variable = "aws:SourceAccount"
      values   = [data.aws_caller_identity.current.account_id]
    }
  }
}

resource "aws_kms_key" "pfg" {
  description             = "partner-file-gateway data at rest"
  enable_key_rotation     = true
  deletion_window_in_days = 30
  policy                  = data.aws_iam_policy_document.kms.json
}

resource "aws_kms_alias" "pfg" {
  name          = "alias/partner-file-gateway"
  target_key_id = aws_kms_key.pfg.key_id
}

module "storage" {
  source = "../../modules/storage"

  bucket_name = "pfg-transfer-${data.aws_caller_identity.current.account_id}"
  kms_key_arn = aws_kms_key.pfg.arn
  tags        = local.tags
}

module "registry" {
  source = "../../modules/registry"

  kms_key_arn         = aws_kms_key.pfg.arn
  deletion_protection = true
  tags                = local.tags
}

module "events" {
  source = "../../modules/events"

  bucket_name = module.storage.bucket_name
  kms_key_arn = aws_kms_key.pfg.arn
  tags        = local.tags
}

module "pipeline" {
  source = "../../modules/pipeline"

  lambda_source_dir = "${local.repo_root}/services/lambdas"
  definition_path   = "${local.repo_root}/statemachine/process_transfer.asl.json"

  bucket_name             = module.storage.bucket_name
  bucket_arn              = module.storage.bucket_arn
  partners_table_name     = module.registry.partners_table_name
  partners_table_arn      = module.registry.partners_table_arn
  transfers_table_name    = module.registry.transfers_table_name
  transfers_table_arn     = module.registry.transfers_table_arn
  notifications_queue_url = module.events.notifications_queue_url
  notifications_queue_arn = module.events.notifications_queue_arn
  dead_letter_queue_url   = module.events.dead_letter_queue_url
  dead_letter_queue_arn   = module.events.dead_letter_queue_arn
  event_rule_name         = module.events.rule_name
  event_rule_arn          = module.events.rule_arn
  kms_key_arn             = aws_kms_key.pfg.arn
  log_retention_days      = 365

  tags = local.tags
}

module "transfer" {
  source = "../../modules/transfer_aws"

  bucket_name = module.storage.bucket_name
  bucket_arn  = module.storage.bucket_arn
  partners    = var.partners
  kms_key_arn = aws_kms_key.pfg.arn
  tags        = local.tags
}
