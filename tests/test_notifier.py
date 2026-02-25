"""Tests for notifier.py — SNS notification with fallback resolution."""

from unittest.mock import MagicMock

from log_monitor.notifier import render_message, resolve_sns_topic, resolve_template, sns_publish


class TestResolveSNSTopic:
    GLOBAL_CONFIG = {
        "defaults": {"severity": "warning"},
        "sns_topics": {
            "critical": "arn:aws:sns:ap-northeast-1:123456789012:critical-alerts",
            "warning": "arn:aws:sns:ap-northeast-1:123456789012:warning-alerts",
            "info": "arn:aws:sns:ap-northeast-1:123456789012:info-alerts",
        },
    }

    def test_global_fallback(self):
        """No overrides → use GLOBAL sns_topics"""
        monitor = {"keyword": "ERROR", "severity": "critical"}
        project = {"sk": "project-b"}
        result = resolve_sns_topic(monitor, project, self.GLOBAL_CONFIG)
        assert result == "arn:aws:sns:ap-northeast-1:123456789012:critical-alerts"

    def test_project_override(self):
        """PROJECT override_sns_topics → use project-level topic"""
        monitor = {"keyword": "ERROR", "severity": "critical"}
        project = {
            "sk": "project-a",
            "override_sns_topics": {
                "critical": "arn:aws:sns:...:project-a-critical",
            },
        }
        result = resolve_sns_topic(monitor, project, self.GLOBAL_CONFIG)
        assert result == "arn:aws:sns:...:project-a-critical"

    def test_monitor_override(self):
        """MONITOR override_sns_topic → highest priority"""
        monitor = {
            "keyword": "OOM",
            "severity": "critical",
            "override_sns_topic": "arn:aws:sns:...:team-b-alerts",
        }
        project = {
            "sk": "project-a",
            "override_sns_topics": {"critical": "arn:aws:sns:...:project-a-critical"},
        }
        result = resolve_sns_topic(monitor, project, self.GLOBAL_CONFIG)
        assert result == "arn:aws:sns:...:team-b-alerts"

    def test_severity_fallback_to_global_default(self):
        """Monitor without severity → use GLOBAL default severity"""
        monitor = {"keyword": "WARN"}  # No severity
        project = {"sk": "project-b"}
        result = resolve_sns_topic(monitor, project, self.GLOBAL_CONFIG)
        assert result == "arn:aws:sns:ap-northeast-1:123456789012:warning-alerts"


class TestResolveTemplate:
    GLOBAL_TEMPLATE = {"subject": "GLOBAL subject", "body": "GLOBAL body"}
    GLOBAL_CONFIG = {"notification_template": GLOBAL_TEMPLATE}

    def test_global_fallback(self):
        monitor = {"keyword": "ERROR"}
        project = {"sk": "project-b"}
        result = resolve_template(monitor, project, self.GLOBAL_CONFIG)
        assert result == self.GLOBAL_TEMPLATE

    def test_project_override(self):
        monitor = {"keyword": "ERROR"}
        project_template = {"subject": "PROJECT subject", "body": "PROJECT body"}
        project = {"sk": "project-a", "notification_template": project_template}
        result = resolve_template(monitor, project, self.GLOBAL_CONFIG)
        assert result == project_template

    def test_monitor_override(self):
        monitor_template = {"subject": "MONITOR subject", "body": "MONITOR body"}
        monitor = {"keyword": "OOM", "notification_template": monitor_template}
        project_template = {"subject": "PROJECT subject", "body": "PROJECT body"}
        project = {"sk": "project-a", "notification_template": project_template}
        result = resolve_template(monitor, project, self.GLOBAL_CONFIG)
        assert result == monitor_template


class TestRenderMessage:
    def test_render_notify(self):
        template = {
            "subject": "[{severity}] {project} - {keyword} 検出",
        }
        project = {"sk": "project-a", "display_name": "Project Alpha", "source_log_group": "/aws/app/shared-logs"}
        monitor = {"keyword": "ERROR", "severity": "critical", "mention": "<!here>"}
        matches = [
            {"message": "ERROR: db failed", "logStreamName": "project-a/s1", "timestamp": 1709218536000},
            {"message": "ERROR: timeout", "logStreamName": "project-a/s1", "timestamp": 1709218537000},
        ]
        global_config = {
            "source_log_group": "/aws/app/shared-logs",
            "max_log_lines": 20,
            "defaults": {"severity": "warning"},
        }

        result = render_message(
            template=template,
            project=project,
            monitor=monitor,
            matches=matches,
            action="NOTIFY",
            global_config=global_config,
            previous_log_lines=["INFO: user login", "INFO: process started"],
        )
        assert "[CRITICAL]" in result["subject"]
        assert "Project Alpha" in result["subject"]
        assert "ERROR" in result["subject"]

        # Check body format
        assert "<!here>" in result["body"]
        assert "検出件数: 2" in result["body"]
        assert "ロググループ: /aws/app/shared-logs" in result["body"]
        assert "ログストリーム: project-a/s1" in result["body"]
        assert "検出したログ本文:\nERROR: db failed\nERROR: timeout" in result["body"]
        assert "検出したログ前のログ:\nINFO: user login\nINFO: process started" in result["body"]

    def test_render_recover(self):
        template = {
            "subject": "[{severity}] {project} - {keyword}",
        }
        project = {"sk": "project-a", "display_name": "Project Alpha"}
        monitor = {"keyword": "ERROR", "severity": "critical"}
        global_config = {
            "source_log_group": "/aws/app/shared-logs",
            "max_log_lines": 20,
            "defaults": {"severity": "warning"},
        }

        result = render_message(template, project, monitor, [], "RECOVER", global_config)
        assert "RECOVER" in result["subject"]
        assert "復旧" in result["body"]
        assert "✅" not in result["body"]  # Emojis should be removed

    def test_render_with_empty_matches(self):
        template = {
            "subject": "[{severity}] {project}",
        }
        project = {"sk": "project-a", "display_name": "Project Alpha"}
        monitor = {"keyword": "ERROR", "severity": "warning"}
        global_config = {
            "source_log_group": "/aws/app/shared-logs",
            "max_log_lines": 20,
            "defaults": {"severity": "warning"},
        }

        result = render_message(template, project, monitor, [], "NOTIFY", global_config)
        assert "検出件数: 0" in result["body"]
        assert "(ログなし)" in result["body"]


class TestSNSPublish:
    def test_publish_success(self):
        mock_client = MagicMock()
        message = {"subject": "Test Subject", "body": "Test Body"}
        sns_publish("arn:aws:sns:...:test-topic", message, client=mock_client)

        import json

        expected_payload = {
            "version": "1.0",
            "source": "custom",
            "content": {"title": "Test Subject", "description": "Test Body"},
        }

        mock_client.publish.assert_called_once_with(
            TopicArn="arn:aws:sns:...:test-topic",
            Subject="Test Subject",
            Message=json.dumps(expected_payload),
        )

    def test_publish_truncates_long_subject(self):
        mock_client = MagicMock()
        long_subject = "A" * 200
        message = {"subject": long_subject, "body": "Body"}
        sns_publish("arn:aws:sns:...:test-topic", message, client=mock_client)

        call_args = mock_client.publish.call_args[1]
        assert len(call_args["Subject"]) == 100

        import json

        payload = json.loads(call_args["Message"])
        assert len(payload["content"]["title"]) == 100

    def test_publish_failure_raises(self):
        mock_client = MagicMock()
        mock_client.publish.side_effect = Exception("SNS error")
        message = {"subject": "Sub", "body": "Body"}

        import pytest

        with pytest.raises(Exception, match="SNS error"):
            sns_publish("arn:aws:sns:...:test-topic", message, client=mock_client)
