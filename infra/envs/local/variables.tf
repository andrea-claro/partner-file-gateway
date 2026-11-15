variable "localstack_endpoint" {
  description = "LocalStack edge endpoint (http://localstack:4566 inside the tools container)."
  type        = string
  default     = "http://localhost:4566"

  validation {
    condition     = can(regex("^http://(localstack|localhost|127\\.0\\.0\\.1):4566$", var.localstack_endpoint))
    error_message = "This environment only targets LocalStack."
  }
}

variable "localstack_access_key" {
  description = "LocalStack dummy access key (not a secret)."
  type        = string
  default     = "test"
}

variable "localstack_secret_key" {
  description = "LocalStack dummy secret key (not a secret)."
  type        = string
  default     = "test"
}

variable "region" {
  description = "AWS region emulated by LocalStack."
  type        = string
  default     = "eu-central-2"
}

variable "enable_debug_target" {
  description = "Copy every inbound Object Created event to the pfg-debug-events queue."
  type        = bool
  default     = true
}
