output "server_id" {
  description = "Transfer Family server id."
  value       = aws_transfer_server.sftp.id
}

output "endpoint" {
  description = "SFTP endpoint host name."
  value       = aws_transfer_server.sftp.endpoint
}
