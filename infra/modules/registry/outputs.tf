output "partners_table_name" {
  description = "Name of the partners table."
  value       = aws_dynamodb_table.partners.name
}

output "partners_table_arn" {
  description = "ARN of the partners table."
  value       = aws_dynamodb_table.partners.arn
}

output "transfers_table_name" {
  description = "Name of the transfers (audit trail) table."
  value       = aws_dynamodb_table.transfers.name
}

output "transfers_table_arn" {
  description = "ARN of the transfers (audit trail) table."
  value       = aws_dynamodb_table.transfers.arn
}
