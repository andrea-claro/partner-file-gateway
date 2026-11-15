# Every endpoint points at LocalStack (var.localstack_endpoint only accepts
# LocalStack addresses) and the credentials are LocalStack's dummy ones, so this
# environment cannot create real AWS resources.
provider "aws" {
  region     = var.region
  access_key = var.localstack_access_key
  secret_key = var.localstack_secret_key

  skip_credentials_validation = true
  skip_metadata_api_check     = true
  # Without an account id the provider uses the plain S3 tagging API instead of
  # S3 Control (whose account-id host prefix does not work with a custom endpoint).
  skip_requesting_account_id = true
  s3_use_path_style          = true

  endpoints {
    cloudwatch     = var.localstack_endpoint
    cloudwatchlogs = var.localstack_endpoint
    dynamodb       = var.localstack_endpoint
    eventbridge    = var.localstack_endpoint
    iam            = var.localstack_endpoint
    kms            = var.localstack_endpoint
    lambda         = var.localstack_endpoint
    s3             = var.localstack_endpoint
    sfn            = var.localstack_endpoint
    sqs            = var.localstack_endpoint
    sts            = var.localstack_endpoint
  }

  default_tags {
    tags = local.tags
  }
}
