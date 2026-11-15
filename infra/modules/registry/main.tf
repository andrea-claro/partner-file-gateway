# partners:  one item per partner (status, allowed patterns, limits, key fingerprint).
# transfers: one item per uploaded object version, with its full status history.

resource "aws_dynamodb_table" "partners" {
  #checkov:skip=CKV_AWS_119:A customer managed key is supported through var.kms_key_arn (used by envs/aws); LocalStack uses the AWS owned key.
  name                        = var.partners_table_name
  billing_mode                = "PAY_PER_REQUEST"
  hash_key                    = "partner_id"
  deletion_protection_enabled = var.deletion_protection

  attribute {
    name = "partner_id"
    type = "S"
  }

  point_in_time_recovery {
    enabled = true
  }

  server_side_encryption {
    enabled     = true
    kms_key_arn = var.kms_key_arn
  }

  tags = merge(var.tags, { Component = "registry" })
}

resource "aws_dynamodb_table" "transfers" {
  #checkov:skip=CKV_AWS_119:A customer managed key is supported through var.kms_key_arn (used by envs/aws); LocalStack uses the AWS owned key.
  name                        = var.transfers_table_name
  billing_mode                = "PAY_PER_REQUEST"
  hash_key                    = "transfer_id"
  deletion_protection_enabled = var.deletion_protection

  attribute {
    name = "transfer_id"
    type = "S"
  }

  attribute {
    name = "partner_id"
    type = "S"
  }

  attribute {
    name = "received_at"
    type = "S"
  }

  # Transfers of one partner, newest first (ScanIndexForward = false).
  global_secondary_index {
    name            = "by_partner"
    projection_type = "ALL"

    key_schema {
      attribute_name = "partner_id"
      key_type       = "HASH"
    }

    key_schema {
      attribute_name = "received_at"
      key_type       = "RANGE"
    }
  }

  point_in_time_recovery {
    enabled = true
  }

  server_side_encryption {
    enabled     = true
    kms_key_arn = var.kms_key_arn
  }

  tags = merge(var.tags, { Component = "registry" })
}
