# CloudWatch Logs Handler

Centralized CloudWatch Logs monitoring solution driven by DynamoDB configurations. This AWS Lambda function periodically queries CloudWatch Logs across multiple projects, identifies keyword matches, evaluates states, and sends severity-based notifications out via Amazon SNS.

## Features

- **Centralized Configuration**: All projects, monitors, string/regex exclusions, and states are centrally managed via a serverless DynamoDB table.
- **Dynamic Log Routing**: Supports custom log streams per project, with the ability to override global log groups.
- **Stateful Notifications**: Tracks the state of log alarms. Suppresses continuous spam during ongoing issues and issues `RECOVER`-type alerts when issues resolve based on a configurable timeframe.
- **Flexible Notifications**: Multi-level SNS resolution. A globally configured topic per-severity can be overridden at the project or monitor level.
- **Custom Metrics**: Emits CloudWatch Metrics (`KeywordDetectionCount`) for creating centralized dashboards across all log monitors.

## Architecture

1. **EventBridge Schedule**: Triggers Lambda every 5 minutes.
2. **Lambda Function (Python 3.12)**: Orchestrator that scans logs using the `FilterLogEvents` API with intelligent time-window handling.
3. **DynamoDB (`log-monitor`)**:
    - `GLOBAL#CONFIG`: Stores universal settings, SNS ARNs, and standard templates.
    - `PROJECT#<project_name>`: Configurations specific to individual systems or services.
    - `STATE#<project>#<keyword>`: Programmatically tracking active alarms, streaks, and timestamps.
4. **SNS**: Notifications destination.

## Deployment Environment

This project supports two deployment methods: AWS SAM (Serverless Application Model) and Terraform. **Since the Lambda function only requires `boto3` (which is built into the Lambda environment), Terraform can upload the source code directly without a heavy build step.**

### Option A: AWS SAM

```bash
# Validate SAM template
sam validate

# Build the project
sam build

# Deploy to AWS (Guided)
sam deploy --guided
```

### Option B: Terraform (Recommended for simple code changes)

Terraform will automatically zip the `src/` directory and calculate its hash, meaning it will only update the Lambda function natively when Python code genuinely changes—eliminating the need for slow builds.

```bash
cd terraform/

# Initialize Terraform providers
terraform init

# Review the infrastructure changes
terraform plan

# Deploy changes to AWS
terraform apply
```

## Setup & Configuration

Once deployed, the `log-monitor` DynamoDB table must be populated with initial configurations.

A seeding script is included to quickly initialize the basic configuration and seed some mock project monitors:

```bash
# Requires AWS credentials configured locally (e.g. AWS_PROFILE)
python scripts/seed_dynamodb.py
```

### Essential DynamoDB Structure
#### Global Settings (`pk: GLOBAL, sk: CONFIG`)
Contains defaults, logging boundaries, and base SNS topics.
```json
{
  "pk": "GLOBAL",
  "sk": "CONFIG",
  "source_log_group": "/aws/app/shared-logs",
  "metric_namespace": "LogMonitor",
  "disable_custom_metrics": false,
  "defaults": {
    "severity": "warning",
    "renotify_min": 60,
    "notify_on_recover": true
  },
  "sns_topics": {
    "critical": "arn:aws:sns:REGION:ACCOUNT:critical-topic",
    "warning": "arn:aws:sns:REGION:ACCOUNT:warning-topic",
    "info": "arn:aws:sns:REGION:ACCOUNT:info-topic"
  },
  "notification_template": {
    "subject": "[{severity}] {project} - {keyword} 検出"
  }
}
```

#### Project Configurations (`pk: PROJECT, sk: <project-name>`)
Defines the projects you want to monitor, stream filters, and active keyword monitors.
```json
{
  "pk": "PROJECT",
  "sk": "project-alpha",
  "display_name": "Project Alpha",
  "stream_prefix": "app-alpha/",
  "enabled": true,
  "monitors": [
    {
      "keyword": ["ERROR", "FATAL", "Exception"],
      "severity": "critical"
    },
    {
      "keyword": "Connection lost",
      "severity": "warning"
    }
  ],
  "exclusions": ["ignored-error", "^regex-exclusion-pattern$"]
}
```

### Full Configuration Sample
Here is a complete example showing all available configuration options, including overrides and context settings.

```json
{
  "pk": "PROJECT",
  "sk": "project-full-sample",
  "display_name": "Full Sample Project",
  "stream_prefix": "app-sample/",
  "enabled": true,
  
  "//": "Optional: Global log group override",
  "override_log_group": "/aws/lambda/custom-group-override",
  
  "//": "Optional: Default context lines to fetch for all monitors in this project",
  "context_log_lines": 5,
  
  "monitors": [
    {
      "keyword": ["ERROR", "FATAL"],
      "severity": "critical",
      
      "//": "Optional: Mention specific users/groups in Slack",
      "mention": "<!here>",
      
      "//": "Optional: Override project-level context lines",
      "context_log_lines": 10,
      
      "//": "Optional: Exclude specific patterns for this monitor",
      "exclude_patterns": ["known-issue-ignore"],
      
      "//": "Optional: Custom notification template (subject only)",
      "notification_template": {
        "subject": "[🚨 CRITICAL] {keyword} observed in {project}"
      }
    }
  ],
  
  "//": "Optional: Project-level exclusions",
  "exclude_patterns": ["debug-log-noise"]
}
```

### Notification Templates

The notification template dictates how the subject line of the SNS message (and Slack alert) is formatted. The message `body` is automatically generated and standardized by the application and cannot be overridden.

You can set `notification_template` at the **GLOBAL**, **PROJECT**, or **MONITOR** level (highest priority wins).

**Available Variables in `subject`:**
- `{project}`: The display name or ID of the project
- `{keyword}`: The keyword that triggered the monitor
- `{severity}`: The severity level (e.g., CRITICAL, WARNING)
- `{count}`: Number of log lines matched
- `{detected_at}`: Timestamp of detection (JST)
- `{log_group}`: The CloudWatch Logs group
- `{stream_name}`: The CloudWatch Log stream names
- `{log_lines}`: The actual log contents
- `{streak}`: The current consecutive detection streak count

## Local Testing & Development

This project was built with Python `pytest` and `moto` for local AWS resource mocking. `uv` is recommended for dependency management.

```bash
# Prepare environment & Install Dev Dependencies
uv venv
source .venv/bin/activate
uv pip install -r requirements-dev.txt

# Run linting
uv run ruff check src/ tests/
uv run ruff format src/ tests/

# Run unit tests
uv run pytest tests/ -v
```
