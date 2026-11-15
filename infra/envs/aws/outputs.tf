output "sftp_endpoint" {
  description = "Transfer Family SFTP endpoint."
  value       = module.transfer.endpoint
}

output "state_machine_arn" {
  description = "process-transfer state machine."
  value       = module.pipeline.state_machine_arn
}
