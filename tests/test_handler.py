"""Integration tests for handler.py — Full Lambda flow."""

from unittest.mock import patch

import boto3
import pytest
from moto import mock_aws

from log_monitor.handler import handler


@pytest.fixture
def full_setup(dynamodb_table, global_config_item, project_a_item):
    """Set up DynamoDB with GLOBAL config and a project, return table."""
    dynamodb_table.put_item(Item=global_config_item)
    dynamodb_table.put_item(Item=project_a_item)
    return dynamodb_table


class TestHandler:
    @mock_aws
    @patch("log_monitor.handler.boto3")
    @patch("log_monitor.handler.filter_log_events_with_pagination")
    @patch("log_monitor.handler.sns_publish")
    @patch("log_monitor.handler.put_metric_data")
    def test_full_flow_with_detections(self, mock_put_metric, mock_sns, mock_filter, mock_boto3):
        """Test complete flow: detect errors → notify → update state."""
        # Set up DynamoDB
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

        # Insert config
        table.put_item(
            Item={
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
                    "subject": "[{severity}] {project} - {keyword}",
                    "body": "{project} で {keyword} が {count}件 検出\n{log_lines}",
                },
            }
        )

        table.put_item(
            Item={
                "pk": "PROJECT",
                "sk": "project-a",
                "display_name": "Project Alpha",
                "stream_prefix": "project-a",
                "enabled": True,
                "monitors": [
                    {"keyword": "ERROR", "severity": "critical"},
                ],
            }
        )

        # Mock boto3.resource to return our mocked DynamoDB
        mock_boto3.resource.return_value = dynamodb

        # Mock log search to return some matches
        mock_filter.return_value = [
            {"message": "ERROR: database failed", "logStreamName": "project-a/s1", "timestamp": 1000},
            {"message": "ERROR: timeout occurred", "logStreamName": "project-a/s1", "timestamp": 2000},
        ]

        # Run handler
        result = handler({}, None)

        # Verify
        assert result["processed_projects"] == 1
        assert result["total_monitors"] == 1
        assert result["total_detections"] == 2
        assert result["notifications_sent"] == 1

        # SNS should have been called for NOTIFY
        mock_sns.assert_called_once()
        call_args = mock_sns.call_args
        assert "arn:aws:sns:ap-northeast-1:123456789012:critical-alerts" == call_args[0][0]

        # Metrics should have been sent
        mock_put_metric.assert_called_once()

        # Check STATE was created in DynamoDB
        state = table.get_item(Key={"pk": "STATE", "sk": "project-a#ERROR"}).get("Item")
        assert state is not None
        assert state["status"] == "ALARM"

    @mock_aws
    @patch("log_monitor.handler.boto3")
    @patch("log_monitor.handler.filter_log_events_with_pagination")
    @patch("log_monitor.handler.sns_publish")
    @patch("log_monitor.handler.put_metric_data")
    def test_metrics_disabled(self, mock_put_metric, mock_sns, mock_filter, mock_boto3):
        """Test put_metric_data is conditionally disabled."""
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

        table.put_item(
            Item={
                "pk": "GLOBAL",
                "sk": "CONFIG",
                "source_log_group": "/aws/app/shared-logs",
                "metric_namespace": "LogMonitor",
                "disable_custom_metrics": True,  # Key metric disable flag
                "defaults": {"severity": "warning", "renotify_min": 60, "notify_on_recover": True},
                "sns_topics": {},
                "notification_template": {"subject": "sub", "body": "body"},
            }
        )

        table.put_item(
            Item={
                "pk": "PROJECT",
                "sk": "project-a",
                "enabled": True,
                "monitors": [{"keyword": "ERROR", "severity": "critical"}],
            }
        )

        mock_boto3.resource.return_value = dynamodb
        mock_filter.return_value = [{"message": "ERROR: fail"}]

        handler({}, None)

        mock_put_metric.assert_not_called()

    @mock_aws
    @patch("log_monitor.handler.boto3")
    @patch("log_monitor.handler.filter_log_events_with_pagination")
    @patch("log_monitor.handler.sns_publish")
    @patch("log_monitor.handler.put_metric_data")
    def test_disabled_project_skipped(self, mock_put_metric, mock_sns, mock_filter, mock_boto3):
        """Disabled projects should be completely skipped."""
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

        table.put_item(
            Item={
                "pk": "GLOBAL",
                "sk": "CONFIG",
                "source_log_group": "/aws/app/shared-logs",
                "metric_namespace": "LogMonitor",
                "max_log_lines": 20,
                "defaults": {"severity": "warning", "renotify_min": 60, "notify_on_recover": True},
                "sns_topics": {
                    "critical": "arn:aws:sns:...:critical",
                    "warning": "arn:aws:sns:...:warning",
                    "info": "arn:aws:sns:...:info",
                },
                "notification_template": {"subject": "sub", "body": "body"},
            }
        )

        table.put_item(
            Item={
                "pk": "PROJECT",
                "sk": "project-disabled",
                "display_name": "Disabled Project",
                "stream_prefix": "disabled",
                "enabled": False,
                "monitors": [{"keyword": "ERROR", "severity": "critical"}],
            }
        )

        mock_boto3.resource.return_value = dynamodb

        result = handler({}, None)

        assert result["processed_projects"] == 0
        mock_filter.assert_not_called()
        mock_sns.assert_not_called()

    @mock_aws
    @patch("log_monitor.handler.boto3")
    @patch("log_monitor.handler.filter_log_events_with_pagination")
    @patch("log_monitor.handler.sns_publish")
    @patch("log_monitor.handler.put_metric_data")
    def test_no_detections_noop(self, mock_put_metric, mock_sns, mock_filter, mock_boto3):
        """No detections and status=OK → NOOP, no notifications."""
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

        table.put_item(
            Item={
                "pk": "GLOBAL",
                "sk": "CONFIG",
                "source_log_group": "/aws/app/shared-logs",
                "metric_namespace": "LogMonitor",
                "max_log_lines": 20,
                "defaults": {"severity": "warning", "renotify_min": 60, "notify_on_recover": True},
                "sns_topics": {
                    "critical": "arn:aws:sns:...:critical",
                    "warning": "arn:aws:sns:...:warning",
                    "info": "arn:aws:sns:...:info",
                },
                "notification_template": {"subject": "sub", "body": "body"},
            }
        )

        table.put_item(
            Item={
                "pk": "PROJECT",
                "sk": "project-a",
                "display_name": "Project Alpha",
                "stream_prefix": "project-a",
                "enabled": True,
                "monitors": [{"keyword": "ERROR", "severity": "critical"}],
            }
        )

        mock_boto3.resource.return_value = dynamodb
        mock_filter.return_value = []

        result = handler({}, None)

        assert result["total_detections"] == 0
        assert result["notifications_sent"] == 0
        mock_sns.assert_not_called()
        # Metrics should still be sent (with value=0)
        mock_put_metric.assert_called_once()
