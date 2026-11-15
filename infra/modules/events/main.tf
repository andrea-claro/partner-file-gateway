# Notifications queue (+ dead-letter queue) and the EventBridge rule that turns
# "Object Created under inbound/" into a pipeline run. The Step Functions target
# is attached by the pipeline module.

locals {
  sqs_managed_sse = var.kms_key_arn == null
  tags            = merge(var.tags, { Component = "events" })
}

resource "aws_sqs_queue" "notifications_dlq" {
  name                      = "${var.notifications_queue_name}-dlq"
  message_retention_seconds = 1209600 # 14 days, the maximum
  sqs_managed_sse_enabled   = local.sqs_managed_sse
  kms_master_key_id         = var.kms_key_arn
  tags                      = local.tags
}

resource "aws_sqs_queue" "notifications" {
  name                       = var.notifications_queue_name
  message_retention_seconds  = 345600 # 4 days
  visibility_timeout_seconds = 60
  sqs_managed_sse_enabled    = local.sqs_managed_sse
  kms_master_key_id          = var.kms_key_arn

  redrive_policy = jsonencode({
    deadLetterTargetArn = aws_sqs_queue.notifications_dlq.arn
    maxReceiveCount     = var.max_receive_count
  })

  tags = local.tags
}

resource "aws_sqs_queue_redrive_allow_policy" "notifications_dlq" {
  queue_url = aws_sqs_queue.notifications_dlq.id

  redrive_allow_policy = jsonencode({
    redrivePermission = "byQueue"
    sourceQueueArns   = [aws_sqs_queue.notifications.arn]
  })
}

resource "aws_cloudwatch_event_rule" "object_created" {
  name           = var.rule_name
  description    = "S3 Object Created under ${var.inbound_prefix} in ${var.bucket_name}"
  event_bus_name = "default"

  event_pattern = jsonencode({
    source        = ["aws.s3"]
    "detail-type" = ["Object Created"]
    detail = {
      bucket = { name = [var.bucket_name] }
      object = { key = [{ prefix = var.inbound_prefix }] }
    }
  })

  tags = local.tags
}

# EventBridge may also dead-letter events it cannot deliver to the state machine
# (pipeline module, target dead_letter_config): allow exactly this rule to write.
data "aws_iam_policy_document" "notifications_dlq" {
  statement {
    sid       = "AllowEventBridgeDeadLetters"
    actions   = ["sqs:SendMessage"]
    resources = [aws_sqs_queue.notifications_dlq.arn]

    principals {
      type        = "Service"
      identifiers = ["events.amazonaws.com"]
    }

    condition {
      test     = "ArnEquals"
      variable = "aws:SourceArn"
      values   = [aws_cloudwatch_event_rule.object_created.arn]
    }
  }
}

resource "aws_sqs_queue_policy" "notifications_dlq" {
  queue_url = aws_sqs_queue.notifications_dlq.id
  policy    = data.aws_iam_policy_document.notifications_dlq.json
}

# --- Optional debug target ----------------------------------------------------

resource "aws_sqs_queue" "debug" {
  count = var.enable_debug_target ? 1 : 0

  name                      = "pfg-debug-events"
  message_retention_seconds = 86400
  sqs_managed_sse_enabled   = local.sqs_managed_sse
  kms_master_key_id         = var.kms_key_arn
  tags                      = local.tags
}

data "aws_iam_policy_document" "debug" {
  count = var.enable_debug_target ? 1 : 0

  statement {
    sid       = "AllowEventBridgeRule"
    actions   = ["sqs:SendMessage"]
    resources = [aws_sqs_queue.debug[0].arn]

    principals {
      type        = "Service"
      identifiers = ["events.amazonaws.com"]
    }

    condition {
      test     = "ArnEquals"
      variable = "aws:SourceArn"
      values   = [aws_cloudwatch_event_rule.object_created.arn]
    }
  }
}

resource "aws_sqs_queue_policy" "debug" {
  count = var.enable_debug_target ? 1 : 0

  queue_url = aws_sqs_queue.debug[0].id
  policy    = data.aws_iam_policy_document.debug[0].json
}

resource "aws_cloudwatch_event_target" "debug" {
  count = var.enable_debug_target ? 1 : 0

  rule      = aws_cloudwatch_event_rule.object_created.name
  target_id = "debug-sqs"
  arn       = aws_sqs_queue.debug[0].arn
}
