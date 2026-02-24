"""Shared test fixtures for log-monitor tests."""

import os

import boto3
import pytest
from moto import mock_aws


@pytest.fixture(autouse=True)
def aws_env():
    """Set dummy AWS credentials for moto."""
    os.environ["AWS_ACCESS_KEY_ID"] = "testing"
    os.environ["AWS_SECRET_ACCESS_KEY"] = "testing"
    os.environ["AWS_SECURITY_TOKEN"] = "testing"
    os.environ["AWS_SESSION_TOKEN"] = "testing"
    os.environ["AWS_DEFAULT_REGION"] = "ap-northeast-1"
    yield
    for key in [
        "AWS_ACCESS_KEY_ID",
        "AWS_SECRET_ACCESS_KEY",
        "AWS_SECURITY_TOKEN",
        "AWS_SESSION_TOKEN",
        "AWS_DEFAULT_REGION",
    ]:
        os.environ.pop(key, None)


@pytest.fixture
def dynamodb_table():
    """Create a mocked DynamoDB log-monitor table."""
    with mock_aws():
        dynamodb = boto3.resource("dynamodb", region_name="ap-northeast-1")
        table = dynamodb.create_table(
            TableName="log-monitor",
            KeySchema=[
                {"AttributeName": "pk", "KeyType": "HASH"},
                {"AttributeName": "sk", "KeyType": "RANGE"},
            ],
            AttributeDefinitions=[
                {"AttributeName": "pk", "AttributeType": "S"},
                {"AttributeName": "sk", "AttributeType": "S"},
            ],
            BillingMode="PAY_PER_REQUEST",
        )
        table.meta.client.get_waiter("table_exists").wait(TableName="log-monitor")
        yield table


@pytest.fixture
def global_config_item():
    """Sample GLOBAL#CONFIG record."""
    return {
        "pk": "GLOBAL",
        "sk": "CONFIG",
        "source_log_group": "/aws/app/shared-logs",
        "metric_namespace": "LogMonitor",
        "max_log_lines": 20,
        "defaults": {
            "severity": "warning",
            "renotify_min": 60,
            "notify_on_recover": True,
        },
        "sns_topics": {
            "critical": "arn:aws:sns:ap-northeast-1:123456789012:critical-alerts",
            "warning": "arn:aws:sns:ap-northeast-1:123456789012:warning-alerts",
            "info": "arn:aws:sns:ap-northeast-1:123456789012:info-alerts",
        },
        "notification_template": {
            "subject": "[{severity}] {project} - {keyword} 検出",
            "body": (
                "🚨 *{project}* で *{keyword}* が {count}件 検出\n"
                "⏰ {detected_at}\n📁 {log_group}\n---\n{log_lines}"
            ),
        },
    }


@pytest.fixture
def project_a_item():
    """Sample PROJECT record for project-a."""
    return {
        "pk": "PROJECT",
        "sk": "project-a",
        "display_name": "Project Alpha",
        "stream_prefix": "project-a",
        "override_log_group": None,
        "enabled": True,
        "exclude_patterns": ["healthcheck", "ping OK"],
        "monitors": [
            {
                "keyword": "ERROR",
                "severity": "critical",
                "exclude_patterns": ["ERROR: connection reset", "ERROR: cache miss"],
            },
            {
                "keyword": "TIMEOUT",
                "severity": "warning",
                "renotify_min": None,
            },
        ],
    }


@pytest.fixture
def project_b_item():
    """Sample minimal PROJECT record for project-b."""
    return {
        "pk": "PROJECT",
        "sk": "project-b",
        "display_name": "Project Beta",
        "stream_prefix": "project-b",
        "enabled": True,
        "monitors": [
            {"keyword": "ERROR", "severity": "critical"},
            {"keyword": "WARN", "severity": "info"},
        ],
    }
