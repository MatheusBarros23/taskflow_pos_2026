output "reports_bucket" {
  description = "Nome do bucket de relatorios."
  value       = aws_s3_bucket.reports.bucket
}

output "logs_bucket" {
  description = "Nome do bucket de logs de acesso."
  value       = aws_s3_bucket.logs.bucket
}

output "app_security_group_id" {
  description = "ID do security group da aplicacao."
  value       = aws_security_group.app.id
}
