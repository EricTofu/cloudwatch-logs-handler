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

This project is deployed using AWS SAM (Serverless Application Model).

```bash
# Validate SAM template
sam validate

# Build the project
sam build

# Deploy to AWS (Guided)
sam deploy --guided
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
      "keyword": "ERROR",
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
