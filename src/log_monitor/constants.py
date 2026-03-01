"""Shared constants for log-monitor."""

from datetime import timedelta, timezone

# JST timezone (+09:00)
JST = timezone(timedelta(hours=9))

# DynamoDB table name
TABLE_NAME = "log-monitor"
