# Local environment: the whole platform on LocalStack. Same modules as
# infra/envs/aws (ADR-005); only endpoints and encryption keys differ.

locals {
  tags = {
    Project     = "partner-file-gateway"
    Environment = "local"
    ManagedBy   = "terraform"
  }
  repo_root = "${path.module}/../../.."
}

module "storage" {
  source = "../../modules/storage"

  bucket_name   = "pfg-transfer"
  force_destroy = true
  tags          = local.tags
}

module "registry" {
  source = "../../modules/registry"

  tags = local.tags
}

module "events" {
  source = "../../modules/events"

  bucket_name         = module.storage.bucket_name
  enable_debug_target = var.enable_debug_target
  tags                = local.tags
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

  tags = local.tags
}
