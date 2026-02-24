"""CloudWatch Logs search with FilterLogEvents API."""

import logging

import boto3
from botocore.config import Config

logger = logging.getLogger(__name__)

# Enable standard retry mode with exponential backoff for throttling
_BOTO_CONFIG = Config(
    retries={"mode": "standard", "max_attempts": 5},
)


def _get_logs_client():
    """Get CloudWatch Logs client with retry configuration."""
    return boto3.client("logs", config=_BOTO_CONFIG)


def iso_to_epoch_ms(iso_string):
    """Convert ISO 8601 timestamp string to epoch milliseconds.

    Args:
        iso_string: ISO 8601 timestamp string (e.g. "2026-02-20T05:10:00Z").

    Returns:
        int: Epoch time in milliseconds.
    """
    from datetime import datetime

    dt = datetime.fromisoformat(iso_string.replace("Z", "+00:00"))
    return int(dt.timestamp() * 1000)


def filter_log_events_with_pagination(log_group, stream_prefix, keyword, start_time, end_time, client=None):
    """Search CloudWatch Logs using FilterLogEvents with pagination.

    Args:
        log_group: CloudWatch Logs log group name.
        stream_prefix: Log stream name prefix to filter.
        keyword: Keyword to search for in log messages.
        start_time: Search start time (ISO 8601 string).
        end_time: Search end time (ISO 8601 string).
        client: Optional boto3 logs client (for testing).

    Returns:
        list[dict]: Matching log events, each with keys:
            - message: Log message content
            - logStreamName: Name of the log stream
            - timestamp: Event timestamp in milliseconds
    """
    client = client or _get_logs_client()

    start_ms = iso_to_epoch_ms(start_time)
    end_ms = iso_to_epoch_ms(end_time)

    kwargs = {
        "logGroupName": log_group,
        "startTime": start_ms,
        "endTime": end_ms,
        "filterPattern": f'"{keyword}"',
        "interleaved": True,
    }

    # Only add stream prefix filter if provided
    if stream_prefix:
        kwargs["logStreamNamePrefix"] = stream_prefix

    all_events = []

    while True:
        response = client.filter_log_events(**kwargs)
        events = response.get("events", [])
        all_events.extend(events)

        next_token = response.get("nextToken")
        if not next_token:
            break
        kwargs["nextToken"] = next_token

    logger.info(
        "FilterLogEvents: log_group=%s, prefix=%s, keyword=%s, found=%d",
        log_group,
        stream_prefix,
        keyword,
        len(all_events),
    )

    return all_events
