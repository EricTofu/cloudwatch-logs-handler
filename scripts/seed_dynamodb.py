#!/usr/bin/env python3
"""Seed DynamoDB log-monitor table with sample GLOBAL and PROJECT records.

Usage:
    python scripts/seed_dynamodb.py [--table-name log-monitor] [--region ap-northeast-1]
"""

import argparse
import json

import boto3


GLOBAL_CONFIG = {
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
            "⏰ {detected_at}\n"
            "📁 {log_group}\n"
            "---\n"
            "{log_lines}"
        ),
    },
}

SAMPLE_PROJECT = {
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
        {
            "keyword": "OOM",
            "severity": "critical",
            "override_sns_topic": "arn:aws:sns:ap-northeast-1:123456789012:team-b-alerts",
            "notification_template": {
                "subject": "[OOM] Project Alpha - 緊急",
                "body": "💀 *OOM 発生！*\n即時対応が必要です\n---\n{log_lines}",
            },
        },
    ],
}

SAMPLE_PROJECT_MINIMAL = {
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


def seed(table_name, region):
    """Seed the DynamoDB table with sample data."""
    dynamodb = boto3.resource("dynamodb", region_name=region)
    table = dynamodb.Table(table_name)

    records = [GLOBAL_CONFIG, SAMPLE_PROJECT, SAMPLE_PROJECT_MINIMAL]

    for record in records:
        # Convert None values to appropriate DynamoDB format
        clean = json.loads(json.dumps(record, default=str), parse_float=str)
        table.put_item(Item=record)
        print(f"✅ Inserted: pk={record['pk']}, sk={record['sk']}")

    print(f"\n🎉 Seeded {len(records)} records into {table_name}")


def main():
    parser = argparse.ArgumentParser(description="Seed DynamoDB log-monitor table")
    parser.add_argument("--table-name", default="log-monitor", help="DynamoDB table name")
    parser.add_argument("--region", default="ap-northeast-1", help="AWS region")
    args = parser.parse_args()

    seed(args.table_name, args.region)


if __name__ == "__main__":
    main()
