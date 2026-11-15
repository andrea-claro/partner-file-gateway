variable "name_prefix" {
  description = "Prefix for Lambda functions, roles and log groups."
  type        = string
  default     = "pfg"
}

variable "state_machine_name" {
  description = "Name of the Step Functions state machine."
  type        = string
  default     = "process-transfer"
}

variable "lambda_source_dir" {
  description = "Directory containing one folder per function plus pfg_lambda_common/."
  type        = string
}

variable "definition_path" {
  description = "Path of the ASL template (statemachine/process_transfer.asl.json)."
  type        = string
}

variable "bucket_name" {
  description = "Transfer bucket name."
  type        = string
}

variable "bucket_arn" {
  description = "Transfer bucket ARN."
  type        = string
}

variable "partners_table_name" {
  description = "Partners table name."
  type        = string
}

variable "partners_table_arn" {
  description = "Partners table ARN."
  type        = string
}

variable "transfers_table_name" {
  description = "Transfers (audit trail) table name."
  type        = string
}

variable "transfers_table_arn" {
  description = "Transfers (audit trail) table ARN."
  type        = string
}

variable "notifications_queue_url" {
  description = "Notifications queue URL."
  type        = string
}

variable "notifications_queue_arn" {
  description = "Notifications queue ARN."
  type        = string
}

variable "dead_letter_queue_url" {
  description = "Dead-letter queue URL."
  type        = string
}

variable "dead_letter_queue_arn" {
  description = "Dead-letter queue ARN."
  type        = string
}

variable "event_rule_name" {
  description = "EventBridge rule that starts the state machine."
  type        = string
}

variable "event_rule_arn" {
  description = "ARN of that rule (scopes the EventBridge role trust policy)."
  type        = string
}

variable "kms_key_arn" {
  description = "KMS key used by the bucket, tables, queues and log groups (null = AWS managed encryption)."
  type        = string
  default     = null
}

variable "max_file_size_bytes" {
  description = "Default maximum file size when a partner has no limit of its own."
  type        = number
  default     = 10485760
}

variable "log_level" {
  description = "LOG_LEVEL of the Lambda functions."
  type        = string
  default     = "INFO"

  validation {
    condition     = contains(["DEBUG", "INFO", "WARNING", "ERROR"], var.log_level)
    error_message = "log_level must be DEBUG, INFO, WARNING or ERROR."
  }
}

variable "log_retention_days" {
  description = "Retention of the Lambda and state machine log groups."
  type        = number
  default     = 30
}

variable "lambda_architecture" {
  description = "Lambda CPU architecture (x86_64 or arm64)."
  type        = string
  default     = "x86_64"
}

variable "tags" {
  description = "Tags applied to every resource."
  type        = map(string)
  default     = {}
}
