output "bucket_name" {
  description = "Transfer bucket."
  value       = module.storage.bucket_name
}

output "partners_table" {
  description = "Partners table."
  value       = module.registry.partners_table_name
}

output "transfers_table" {
  description = "Transfers (audit trail) table."
  value       = module.registry.transfers_table_name
}

output "notifications_queue_url" {
  description = "Notifications queue."
  value       = module.events.notifications_queue_url
}

output "dead_letter_queue_url" {
  description = "Dead-letter queue."
  value       = module.events.dead_letter_queue_url
}

output "debug_queue_url" {
  description = "Debug copy of every inbound event (null when disabled)."
  value       = module.events.debug_queue_url
}

output "state_machine_arn" {
  description = "process-transfer state machine."
  value       = module.pipeline.state_machine_arn
}
