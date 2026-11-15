variable "region" {
  description = "AWS region."
  type        = string
  default     = "eu-central-2"
}

variable "allowed_account_ids" {
  description = "Accounts Terraform may touch. The default matches no real account on purpose."
  type        = list(string)
  default     = ["000000000000"]
}

variable "partners" {
  description = "Partner id => OpenSSH public key, provisioned on Transfer Family."
  type        = map(string)
  default     = {}
}
