output "lambda_function_arn" {
  description = "ARN of the deployed Lambda function"
  value       = aws_lambda_function.log_monitor.arn
}

output "dynamodb_table_name" {
  description = "Name of the DynamoDB configuration table"
  value       = aws_dynamodb_table.log_monitor.name
}
