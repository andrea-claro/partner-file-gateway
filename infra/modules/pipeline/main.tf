# Processing pipeline: four Lambdas, the process-transfer state machine and the
# EventBridge target that starts it. Every role gets only the actions and
# resources its step needs (CLAUDE.md: no "*" actions on "*" resources).

locals {
  tags = merge(var.tags, { Component = "pipeline" })

  # s3_read / s3_write / s3_delete are key prefixes inside the transfer bucket.
  functions = {
    extract_metadata = {
      description   = "Identify the partner and fingerprint an uploaded file"
      timeout       = 60
      memory        = 256
      s3_read       = ["inbound/"]
      s3_write      = []
      s3_delete     = []
      read_partners = false
    }
    validate = {
      description   = "Check partner status, file name, size and content schema"
      timeout       = 60
      memory        = 256
      s3_read       = ["inbound/"]
      s3_write      = []
      s3_delete     = []
      read_partners = true
    }
    route = {
      description   = "Move an accepted file to processed/"
      timeout       = 60
      memory        = 128
      s3_read       = ["inbound/"]
      s3_write      = ["processed/"]
      s3_delete     = ["inbound/"]
      read_partners = false
    }
    quarantine = {
      description   = "Move a rejected file to quarantine/"
      timeout       = 60
      memory        = 128
      s3_read       = ["inbound/"]
      s3_write      = ["quarantine/"]
      s3_delete     = ["inbound/"]
      read_partners = false
    }
  }

  function_names = { for key, _ in local.functions : key => "${var.name_prefix}-${replace(key, "_", "-")}" }
}

# --- Packaging ------------------------------------------------------------------

# Each zip holds the function's folder plus the shared pfg_lambda_common package.
data "archive_file" "function" {
  for_each = local.functions

  type        = "zip"
  output_path = "${path.root}/.build/${each.key}.zip"

  dynamic "source" {
    for_each = setunion(
      fileset(var.lambda_source_dir, "${each.key}/**/*.py"),
      fileset(var.lambda_source_dir, "pfg_lambda_common/**/*.py"),
    )

    content {
      content  = file("${var.lambda_source_dir}/${source.value}")
      filename = source.value
    }
  }
}

# --- Lambda functions -------------------------------------------------------------

resource "aws_cloudwatch_log_group" "lambda" {
  #checkov:skip=CKV_AWS_158:KMS for log groups is supported through var.kms_key_arn (envs/aws).
  #checkov:skip=CKV_AWS_338:30 days is enough for a demo; raise log_retention_days for compliance needs.
  for_each = local.functions

  name              = "/aws/lambda/${local.function_names[each.key]}"
  retention_in_days = var.log_retention_days
  kms_key_id        = var.kms_key_arn
  tags              = local.tags
}

data "aws_iam_policy_document" "lambda_assume" {
  statement {
    actions = ["sts:AssumeRole"]

    principals {
      type        = "Service"
      identifiers = ["lambda.amazonaws.com"]
    }
  }
}

resource "aws_iam_role" "lambda" {
  for_each = local.functions

  name               = "${local.function_names[each.key]}-lambda"
  assume_role_policy = data.aws_iam_policy_document.lambda_assume.json
  tags               = local.tags
}

data "aws_iam_policy_document" "lambda" {
  for_each = local.functions

  statement {
    sid       = "WriteOwnLogs"
    actions   = ["logs:CreateLogStream", "logs:PutLogEvents"]
    resources = ["${aws_cloudwatch_log_group.lambda[each.key].arn}:*"]
  }

  dynamic "statement" {
    for_each = length(each.value.s3_read) > 0 ? [1] : []
    content {
      sid       = "ReadObjects"
      actions   = ["s3:GetObject", "s3:GetObjectVersion"]
      resources = [for prefix in each.value.s3_read : "${var.bucket_arn}/${prefix}*"]
    }
  }

  dynamic "statement" {
    for_each = length(each.value.s3_write) > 0 ? [1] : []
    content {
      sid       = "WriteObjects"
      actions   = ["s3:PutObject"]
      resources = [for prefix in each.value.s3_write : "${var.bucket_arn}/${prefix}*"]
    }
  }

  dynamic "statement" {
    for_each = length(each.value.s3_delete) > 0 ? [1] : []
    content {
      sid       = "DeleteObjects"
      actions   = ["s3:DeleteObject"]
      resources = [for prefix in each.value.s3_delete : "${var.bucket_arn}/${prefix}*"]
    }
  }

  dynamic "statement" {
    for_each = each.value.read_partners ? [1] : []
    content {
      sid       = "ReadPartners"
      actions   = ["dynamodb:GetItem"]
      resources = [var.partners_table_arn]
    }
  }

  dynamic "statement" {
    for_each = var.kms_key_arn == null ? [] : [1]
    content {
      sid       = "UseDataKey"
      actions   = ["kms:Decrypt", "kms:GenerateDataKey"]
      resources = [var.kms_key_arn]
    }
  }
}

resource "aws_iam_role_policy" "lambda" {
  for_each = local.functions

  name   = "least-privilege"
  role   = aws_iam_role.lambda[each.key].id
  policy = data.aws_iam_policy_document.lambda[each.key].json
}

resource "aws_lambda_function" "this" {
  #checkov:skip=CKV_AWS_116:Invoked synchronously by Step Functions, which retries and dead-letters failures.
  #checkov:skip=CKV_AWS_117:The functions only call S3 and DynamoDB; no VPC resources to reach.
  #checkov:skip=CKV_AWS_173:Environment variables hold names only, no secrets.
  #checkov:skip=CKV_AWS_272:Code signing needs AWS Signer, which is not emulated locally.
  #checkov:skip=CKV_AWS_115:Concurrency is bounded by the state machine; reserved concurrency can fail on small real accounts.
  #checkov:skip=CKV_AWS_50:X-Ray is not emulated locally; correlation uses transfer_id in structured logs.
  for_each = local.functions

  function_name    = local.function_names[each.key]
  description      = each.value.description
  role             = aws_iam_role.lambda[each.key].arn
  runtime          = "python3.12"
  handler          = "${each.key}.handler.handler"
  architectures    = [var.lambda_architecture]
  filename         = data.archive_file.function[each.key].output_path
  source_code_hash = data.archive_file.function[each.key].output_base64sha256
  timeout          = each.value.timeout
  memory_size      = each.value.memory

  environment {
    variables = {
      LOG_LEVEL           = var.log_level
      TRANSFER_BUCKET     = var.bucket_name
      PARTNERS_TABLE      = var.partners_table_name
      MAX_FILE_SIZE_BYTES = tostring(var.max_file_size_bytes)
    }
  }

  tags = local.tags

  depends_on = [aws_cloudwatch_log_group.lambda, aws_iam_role_policy.lambda]
}

# --- State machine ----------------------------------------------------------------

resource "aws_cloudwatch_log_group" "state_machine" {
  #checkov:skip=CKV_AWS_158:KMS for log groups is supported through var.kms_key_arn (envs/aws).
  #checkov:skip=CKV_AWS_338:30 days is enough for a demo; raise log_retention_days for compliance needs.
  name              = "/aws/vendedlogs/states/${var.state_machine_name}"
  retention_in_days = var.log_retention_days
  kms_key_id        = var.kms_key_arn
  tags              = local.tags
}

data "aws_iam_policy_document" "states_assume" {
  statement {
    actions = ["sts:AssumeRole"]

    principals {
      type        = "Service"
      identifiers = ["states.amazonaws.com"]
    }
  }
}

resource "aws_iam_role" "state_machine" {
  name               = "${var.name_prefix}-${var.state_machine_name}-sfn"
  assume_role_policy = data.aws_iam_policy_document.states_assume.json
  tags               = local.tags
}

data "aws_iam_policy_document" "state_machine" {
  statement {
    sid     = "InvokePipelineFunctions"
    actions = ["lambda:InvokeFunction"]
    resources = flatten([
      for fn in aws_lambda_function.this : [fn.arn, "${fn.arn}:*"]
    ])
  }

  statement {
    sid       = "WriteAuditTrail"
    actions   = ["dynamodb:PutItem", "dynamodb:UpdateItem"]
    resources = [var.transfers_table_arn]
  }

  statement {
    sid       = "SendNotifications"
    actions   = ["sqs:SendMessage"]
    resources = [var.notifications_queue_arn, var.dead_letter_queue_arn]
  }

  # CloudWatch Logs delivery for Step Functions does not support resource-level
  # permissions: AWS requires Resource "*" for these specific actions.
  statement {
    sid = "DeliverExecutionLogs"
    actions = [
      "logs:CreateLogDelivery",
      "logs:GetLogDelivery",
      "logs:UpdateLogDelivery",
      "logs:DeleteLogDelivery",
      "logs:ListLogDeliveries",
      "logs:PutResourcePolicy",
      "logs:DescribeResourcePolicies",
      "logs:DescribeLogGroups",
    ]
    resources = ["*"]
  }

  dynamic "statement" {
    for_each = var.kms_key_arn == null ? [] : [1]
    content {
      sid       = "UseDataKey"
      actions   = ["kms:Decrypt", "kms:GenerateDataKey"]
      resources = [var.kms_key_arn]
    }
  }
}

resource "aws_iam_role_policy" "state_machine" {
  name   = "least-privilege"
  role   = aws_iam_role.state_machine.id
  policy = data.aws_iam_policy_document.state_machine.json
}

resource "aws_sfn_state_machine" "process_transfer" {
  #checkov:skip=CKV_AWS_284:X-Ray is not emulated locally; correlation uses transfer_id.
  name     = var.state_machine_name
  role_arn = aws_iam_role.state_machine.arn
  type     = "STANDARD"

  definition = templatefile(var.definition_path, {
    extract_metadata_arn    = aws_lambda_function.this["extract_metadata"].arn
    validate_arn            = aws_lambda_function.this["validate"].arn
    route_arn               = aws_lambda_function.this["route"].arn
    quarantine_arn          = aws_lambda_function.this["quarantine"].arn
    transfers_table         = var.transfers_table_name
    notifications_queue_url = var.notifications_queue_url
    dead_letter_queue_url   = var.dead_letter_queue_url
  })

  logging_configuration {
    log_destination        = "${aws_cloudwatch_log_group.state_machine.arn}:*"
    include_execution_data = true
    level                  = "ERROR"
  }

  tags = local.tags

  depends_on = [aws_iam_role_policy.state_machine]
}

# --- EventBridge -> Step Functions ------------------------------------------------

data "aws_iam_policy_document" "events_assume" {
  statement {
    actions = ["sts:AssumeRole"]

    principals {
      type        = "Service"
      identifiers = ["events.amazonaws.com"]
    }

    condition {
      test     = "ArnEquals"
      variable = "aws:SourceArn"
      values   = [var.event_rule_arn]
    }
  }
}

resource "aws_iam_role" "events" {
  name               = "${var.name_prefix}-${var.state_machine_name}-events"
  assume_role_policy = data.aws_iam_policy_document.events_assume.json
  tags               = local.tags
}

data "aws_iam_policy_document" "events" {
  statement {
    sid       = "StartProcessTransfer"
    actions   = ["states:StartExecution"]
    resources = [aws_sfn_state_machine.process_transfer.arn]
  }
}

resource "aws_iam_role_policy" "events" {
  name   = "start-state-machine"
  role   = aws_iam_role.events.id
  policy = data.aws_iam_policy_document.events.json
}

resource "aws_cloudwatch_event_target" "process_transfer" {
  rule      = var.event_rule_name
  target_id = "process-transfer"
  arn       = aws_sfn_state_machine.process_transfer.arn
  role_arn  = aws_iam_role.events.arn

  retry_policy {
    maximum_event_age_in_seconds = 3600
    maximum_retry_attempts       = 10
  }

  dead_letter_config {
    arn = var.dead_letter_queue_arn
  }
}
