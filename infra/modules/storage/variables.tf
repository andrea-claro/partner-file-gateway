variable "bucket_name" {
  description = "Name of the transfer bucket (inbound/, processed/, quarantine/)."
  type        = string
}

variable "kms_key_arn" {
  description = "KMS key for SSE-KMS. null uses SSE-S3 (AES256), e.g. on LocalStack."
  type        = string
  default     = null
}

variable "force_destroy" {
  description = "Allow terraform destroy to delete a non-empty bucket (local only)."
  type        = bool
  default     = false
}

variable "noncurrent_version_retention_days" {
  description = "Days to keep overwritten or moved object versions."
  type        = number
  default     = 30
}

variable "quarantine_retention_days" {
  description = "Days to keep quarantined files."
  type        = number
  default     = 90
}

variable "tags" {
  description = "Tags applied to every resource."
  type        = map(string)
  default     = {}
}
