variable "bucket_name" {
  description = "Transfer bucket whose Object Created events start the pipeline."
  type        = string
}

variable "inbound_prefix" {
  description = "Only objects under this prefix are transfers."
  type        = string
  default     = "inbound/"
}

variable "notifications_queue_name" {
  description = "SQS queue for transfer outcome notifications."
  type        = string
  default     = "partner-notifications"
}

variable "rule_name" {
  description = "EventBridge rule matching Object Created under the inbound prefix."
  type        = string
  default     = "pfg-inbound-object-created"
}

variable "max_receive_count" {
  description = "Deliveries of a notification before it moves to the dead-letter queue."
  type        = number
  default     = 5
}

variable "enable_debug_target" {
  description = "Also copy every matching event to an SQS debug queue (local troubleshooting)."
  type        = bool
  default     = false
}

variable "kms_key_arn" {
  description = "KMS key for SQS encryption. null uses SQS managed encryption (SSE-SQS)."
  type        = string
  default     = null
}

variable "tags" {
  description = "Tags applied to every resource."
  type        = map(string)
  default     = {}
}
