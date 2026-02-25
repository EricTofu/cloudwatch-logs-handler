variable "aws_region" {
  type        = string
  description = "AWS Region to deploy to"
  default     = "ap-northeast-1"
}

variable "environment" {
  type        = string
  description = "Deployment environment (e.g. dev, staging, prod)"
  default     = "dev"
}

variable "schedule_expression" {
  type        = string
  description = "EventBridge schedule expression for the Lambda trigger"
  default     = "rate(5 minutes)"
}

variable "critical_sns_topic_arn" {
  type        = string
  description = "SNS topic ARN for critical alerts"
  default     = "*" # Default to * if not provided out of the box so IAM allows any. Ideally, provide specific ARN.
}

variable "warning_sns_topic_arn" {
  type        = string
  description = "SNS topic ARN for warning alerts"
  default     = "*"
}

variable "info_sns_topic_arn" {
  type        = string
  description = "SNS topic ARN for info alerts"
  default     = "*"
}
