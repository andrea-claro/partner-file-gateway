variable "name" {
  description = "Name of the Transfer Family server."
  type        = string
  default     = "pfg-sftp"
}

variable "bucket_name" {
  description = "Transfer bucket; partners land in inbound/<partner>/."
  type        = string
}

variable "bucket_arn" {
  description = "Transfer bucket ARN."
  type        = string
}

variable "partners" {
  description = "Partners allowed to connect: partner id => OpenSSH public key."
  type        = map(string)
  default     = {}

  validation {
    condition     = alltrue([for id in keys(var.partners) : can(regex("^[a-z0-9](?:[a-z0-9-]{0,30}[a-z0-9])?$", id))])
    error_message = "Partner ids must be 1-32 lowercase letters, digits or inner dashes."
  }
}

variable "security_policy_name" {
  description = "Transfer Family security policy (ciphers, KEX, MACs)."
  type        = string
  default     = "TransferSecurityPolicy-2025-03" # includes hybrid post-quantum key exchange
}

variable "kms_key_arn" {
  description = "KMS key protecting the bucket and the log group."
  type        = string
  default     = null
}

variable "log_retention_days" {
  description = "Retention of the server's structured logs."
  type        = number
  default     = 365
}

variable "tags" {
  description = "Tags applied to every resource."
  type        = map(string)
  default     = {}
}
