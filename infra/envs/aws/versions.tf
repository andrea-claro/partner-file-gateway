terraform {
  required_version = ">= 1.6"

  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 6.73"
    }
    archive = {
      source  = "hashicorp/archive"
      version = "~> 2.8"
    }
  }

  # VALIDATE ONLY. This project never runs plan or apply here (zero cloud cost).
  # A real deployment would use a remote backend such as:
  #   backend "s3" { bucket = "...", key = "pfg/aws.tfstate", region = "eu-central-2", use_lockfile = true }
}
