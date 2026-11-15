# Safety net: the placeholder account id below matches no real AWS account, so
# even an accidental `terraform apply` with real credentials fails before
# creating anything. A real deployment would set allowed_account_ids explicitly.
provider "aws" {
  region              = var.region
  allowed_account_ids = var.allowed_account_ids

  default_tags {
    tags = local.tags
  }
}
