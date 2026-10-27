variable "aws_region" {
  description = "Regiao AWS dos recursos."
  type        = string
  default     = "us-east-1"
}

variable "project" {
  description = "Nome do projeto, usado em nomes e tags."
  type        = string
  default     = "taskflow"
}

variable "environment" {
  description = "Ambiente (ex.: estudo, staging, prod)."
  type        = string
  default     = "estudo"
}

variable "owner" {
  description = "Responsavel pelos recursos."
  type        = string
  default     = "grupo-devsecops"
}

variable "bucket_suffix" {
  description = "Sufixo unico para os nomes dos buckets (nomes S3 sao globais)."
  type        = string
  default     = "pos-2026"
}

variable "vpc_id" {
  description = "VPC onde o security group sera criado."
  type        = string
}

variable "allowed_ssh_cidr" {
  description = "Unica faixa CIDR autorizada a acessar SSH (porta 22)."
  type        = string

  validation {
    condition     = can(cidrhost(var.allowed_ssh_cidr, 0)) && var.allowed_ssh_cidr != "0.0.0.0/0"
    error_message = "Informe um CIDR valido e restrito; 0.0.0.0/0 nao e permitido."
  }
}

variable "allowed_egress_cidrs" {
  description = "Destinos (CIDR) permitidos para saida HTTPS, ex.: proxy ou VPC endpoints."
  type        = list(string)

  validation {
    condition     = length(var.allowed_egress_cidrs) > 0 && alltrue([for c in var.allowed_egress_cidrs : can(cidrhost(c, 0)) && c != "0.0.0.0/0"])
    error_message = "Informe ao menos um CIDR valido e restrito; 0.0.0.0/0 nao e permitido."
  }
}

variable "log_retention_days" {
  description = "Dias de retencao dos logs de acesso do bucket."
  type        = number
  default     = 365
}
