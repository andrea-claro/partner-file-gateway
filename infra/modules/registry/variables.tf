variable "partners_table_name" {
  description = "DynamoDB table holding partner records."
  type        = string
  default     = "partners"
}

variable "transfers_table_name" {
  description = "DynamoDB table holding the per-transfer audit trail."
  type        = string
  default     = "transfers"
}

variable "kms_key_arn" {
  description = "KMS key for table encryption. null uses the AWS owned key."
  type        = string
  default     = null
}

variable "deletion_protection" {
  description = "Protect tables from deletion (enable on real AWS)."
  type        = bool
  default     = false
}

variable "tags" {
  description = "Tags applied to every resource."
  type        = map(string)
  default     = {}
}
