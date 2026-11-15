output "bucket_name" {
  description = "Name of the transfer bucket."
  value       = aws_s3_bucket.transfer.id
}

output "bucket_arn" {
  description = "ARN of the transfer bucket."
  value       = aws_s3_bucket.transfer.arn
}
