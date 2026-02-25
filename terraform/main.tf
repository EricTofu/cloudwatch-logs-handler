terraform {
  required_version = ">= 1.5.0"
  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 5.0"
    }
    archive = {
      source  = "hashicorp/archive"
      version = "~> 2.4"
    }
  }
}

provider "aws" {
  region = var.aws_region
}

# ------------------------------------------------------------------------------
# DynamoDB Table
# ------------------------------------------------------------------------------
resource "aws_dynamodb_table" "log_monitor" {
  name         = "log-monitor"
  billing_mode = "PAY_PER_REQUEST"
  hash_key     = "pk"
  range_key    = "sk"

  attribute {
    name = "pk"
    type = "S"
  }

  attribute {
    name = "sk"
    type = "S"
  }

  tags = {
    Environment = var.environment
  }
}

# ------------------------------------------------------------------------------
# Archive Lambda Source
# ------------------------------------------------------------------------------
# Automatically zip the Python source code.
# Terraform will detect changes in the `src/` directory and update the Lambda.
data "archive_file" "lambda_zip" {
  type        = "zip"
  source_dir  = "${path.module}/../src"
  output_path = "${path.module}/.terraform/lambda_function.zip"
}

# ------------------------------------------------------------------------------
# Lambda IAM Role
# ------------------------------------------------------------------------------
data "aws_iam_policy_document" "lambda_assume_role" {
  statement {
    actions = ["sts:AssumeRole"]
    principals {
      type        = "Service"
      identifiers = ["lambda.amazonaws.com"]
    }
  }
}

resource "aws_iam_role" "lambda_exec" {
  name               = "log-monitor-lambda-exec-${var.environment}"
  assume_role_policy = data.aws_iam_policy_document.lambda_assume_role.json
}

# Attach basic execution role (CloudWatch Logs creation for Lambda itself)
resource "aws_iam_role_policy_attachment" "lambda_basic_execution" {
  role       = aws_iam_role.lambda_exec.name
  policy_arn = "arn:aws:iam::aws:policy/service-role/AWSLambdaBasicExecutionRole"
}

# Custom policy for our Lambda's permissions
data "aws_iam_policy_document" "lambda_policy" {
  # DynamoDB read/write
  statement {
    effect = "Allow"
    actions = [
      "dynamodb:PutItem",
      "dynamodb:GetItem",
      "dynamodb:UpdateItem",
      "dynamodb:DeleteItem",
      "dynamodb:Query",
      "dynamodb:Scan"
    ]
    resources = [
      aws_dynamodb_table.log_monitor.arn,
      "${aws_dynamodb_table.log_monitor.arn}/index/*"
    ]
  }

  # CloudWatch Logs read
  statement {
    effect = "Allow"
    actions = [
      "logs:FilterLogEvents",
      "logs:DescribeLogGroups",
      "logs:DescribeLogStreams"
    ]
    resources = ["arn:aws:logs:*:*:log-group:*"]
  }

  # SNS publish
  statement {
    effect = "Allow"
    actions = [
      "sns:Publish"
    ]
    resources = compact([
      var.critical_sns_topic_arn,
      var.warning_sns_topic_arn,
      var.info_sns_topic_arn
    ])
  }

  # CloudWatch metrics
  statement {
    effect = "Allow"
    actions = [
      "cloudwatch:PutMetricData"
    ]
    resources = ["*"]
  }
}

resource "aws_iam_role_policy" "lambda_policy" {
  name   = "log-monitor-policy-${var.environment}"
  role   = aws_iam_role.lambda_exec.id
  policy = data.aws_iam_policy_document.lambda_policy.json
}

# ------------------------------------------------------------------------------
# Lambda Function
# ------------------------------------------------------------------------------
resource "aws_lambda_function" "log_monitor" {
  function_name    = "log-monitor-${var.environment}"
  description      = "CloudWatch Logs keyword monitoring with DynamoDB configuration"
  filename         = data.archive_file.lambda_zip.output_path
  source_code_hash = data.archive_file.lambda_zip.output_base64sha256
  handler          = "log_monitor.handler.handler"
  runtime          = "python3.12"
  timeout          = 300
  memory_size      = 512
  role             = aws_iam_role.lambda_exec.arn

  environment {
    variables = {
      LOG_LEVEL = "INFO"
      # If table name becomes dynamic, pass it here
    }
  }

  tags = {
    Environment = var.environment
  }
}

# ------------------------------------------------------------------------------
# EventBridge Schedule
# ------------------------------------------------------------------------------
resource "aws_cloudwatch_event_rule" "schedule" {
  name                = "log-monitor-schedule-${var.environment}"
  description         = "Trigger log monitoring on a schedule"
  schedule_expression = var.schedule_expression
  state               = "ENABLED"
}

resource "aws_cloudwatch_event_target" "lambda_target" {
  rule      = aws_cloudwatch_event_rule.schedule.name
  target_id = "logMonitorFunction"
  arn       = aws_lambda_function.log_monitor.arn
}

resource "aws_lambda_permission" "allow_eventbridge" {
  statement_id  = "AllowExecutionFromEventBridge"
  action        = "lambda:InvokeFunction"
  function_name = aws_lambda_function.log_monitor.function_name
  principal     = "events.amazonaws.com"
  source_arn    = aws_cloudwatch_event_rule.schedule.arn
}
