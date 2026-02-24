"""CloudWatch custom metrics for keyword detection counts."""

import logging

import boto3

logger = logging.getLogger(__name__)


def put_metric_data(namespace, project, keyword, value, client=None):
    """Send KeywordDetectionCount metric to CloudWatch.

    Args:
        namespace: CloudWatch metric namespace (e.g. "LogMonitor").
        project: Project identifier (sort key).
        keyword: Monitor keyword.
        value: Detection count (after exclusions).
        client: Optional boto3 CloudWatch client (for testing).
    """
    client = client or boto3.client("cloudwatch")

    try:
        client.put_metric_data(
            Namespace=namespace,
            MetricData=[
                {
                    "MetricName": "KeywordDetectionCount",
                    "Dimensions": [
                        {"Name": "Project", "Value": project},
                        {"Name": "Keyword", "Value": keyword},
                    ],
                    "Value": value,
                    "Unit": "Count",
                }
            ],
        )
        logger.debug("PutMetricData: %s/%s=%d", project, keyword, value)
    except Exception:
        logger.exception("Failed to put metric data for %s/%s", project, keyword)
        raise
