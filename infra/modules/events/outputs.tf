output "rule_name" {
  description = "Name of the Object Created rule."
  value       = aws_cloudwatch_event_rule.object_created.name
}

output "rule_arn" {
  description = "ARN of the Object Created rule."
  value       = aws_cloudwatch_event_rule.object_created.arn
}

output "notifications_queue_url" {
  description = "URL of the notifications queue."
  value       = aws_sqs_queue.notifications.id
}

output "notifications_queue_arn" {
  description = "ARN of the notifications queue."
  value       = aws_sqs_queue.notifications.arn
}

output "dead_letter_queue_url" {
  description = "URL of the dead-letter queue."
  value       = aws_sqs_queue.notifications_dlq.id
}

output "dead_letter_queue_arn" {
  description = "ARN of the dead-letter queue."
  value       = aws_sqs_queue.notifications_dlq.arn
}

output "debug_queue_url" {
  description = "URL of the debug queue (null when disabled)."
  value       = var.enable_debug_target ? aws_sqs_queue.debug[0].id : null
}
