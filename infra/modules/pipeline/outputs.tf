output "state_machine_arn" {
  description = "ARN of the process-transfer state machine."
  value       = aws_sfn_state_machine.process_transfer.arn
}

output "function_arns" {
  description = "ARNs of the pipeline Lambda functions, by step."
  value       = { for key, fn in aws_lambda_function.this : key => fn.arn }
}
