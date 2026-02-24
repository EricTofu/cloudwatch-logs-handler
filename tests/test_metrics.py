"""Tests for metrics.py — CloudWatch PutMetricData."""

from unittest.mock import MagicMock

import pytest

from log_monitor.metrics import put_metric_data


class TestPutMetricData:
    def test_sends_metric(self):
        mock_client = MagicMock()
        put_metric_data(
            namespace="LogMonitor",
            project="project-a",
            keyword="ERROR",
            value=5,
            client=mock_client,
        )

        mock_client.put_metric_data.assert_called_once()
        call_args = mock_client.put_metric_data.call_args[1]
        assert call_args["Namespace"] == "LogMonitor"

        metric = call_args["MetricData"][0]
        assert metric["MetricName"] == "KeywordDetectionCount"
        assert metric["Value"] == 5
        assert metric["Unit"] == "Count"

        dims = {d["Name"]: d["Value"] for d in metric["Dimensions"]}
        assert dims["Project"] == "project-a"
        assert dims["Keyword"] == "ERROR"

    def test_sends_zero_count(self):
        mock_client = MagicMock()
        put_metric_data(
            namespace="LogMonitor",
            project="project-b",
            keyword="WARN",
            value=0,
            client=mock_client,
        )

        metric = mock_client.put_metric_data.call_args[1]["MetricData"][0]
        assert metric["Value"] == 0

    def test_failure_raises(self):
        mock_client = MagicMock()
        mock_client.put_metric_data.side_effect = Exception("CloudWatch error")

        with pytest.raises(Exception, match="CloudWatch error"):
            put_metric_data(
                namespace="LogMonitor",
                project="project-a",
                keyword="ERROR",
                value=1,
                client=mock_client,
            )
