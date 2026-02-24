"""Lambda handler for CloudWatch Logs monitoring."""

import logging
from datetime import datetime, timedelta, timezone

import boto3

from log_monitor.config import (
    get_global_config,
    query_all_projects,
    query_all_states,
    update_project_timestamp,
    update_state,
    update_state_suppress,
)
from log_monitor.exclusion import apply_exclusions_regex
from log_monitor.log_searcher import filter_log_events_with_pagination
from log_monitor.metrics import put_metric_data
from log_monitor.notifier import render_message, resolve_sns_topic, resolve_template, sns_publish
from log_monitor.state import evaluate_state, find_state

logger = logging.getLogger()
logger.setLevel(logging.INFO)

# JST timezone
JST = timezone(timedelta(hours=9))

# Ingestion delay buffer (minutes)
INGESTION_DELAY_BUFFER_MIN = 2

# Default search window for new projects (minutes)
DEFAULT_SEARCH_WINDOW_MIN = 5


def _now_utc():
    """Get current UTC time."""
    return datetime.now(timezone.utc)


def handler(event, context):
    """Lambda entry point for CloudWatch Logs monitoring.

    Triggered by EventBridge every 5 minutes. For each enabled project:
    1. Searches CloudWatch Logs for configured keywords
    2. Applies exclusion patterns
    3. Sends CloudWatch metrics
    4. Evaluates state transitions
    5. Sends SNS notifications as needed
    6. Updates DynamoDB state

    Args:
        event: EventBridge scheduled event (unused).
        context: Lambda context (unused).

    Returns:
        dict: Summary of processing results.
    """
    dynamodb = boto3.resource("dynamodb")
    table = dynamodb.Table("log-monitor")

    # 1. Load all configuration
    global_config = get_global_config(table)
    projects = query_all_projects(table)
    states = query_all_states(table)

    # Search end time = now - ingestion delay buffer
    now = _now_utc()
    search_end = now - timedelta(minutes=INGESTION_DELAY_BUFFER_MIN)
    search_end_iso = search_end.strftime("%Y-%m-%dT%H:%M:%SZ")

    results = {
        "processed_projects": 0,
        "total_monitors": 0,
        "total_detections": 0,
        "notifications_sent": 0,
    }

    for project in projects:
        # Skip disabled projects
        if not project.get("enabled", True):
            logger.info("Skipping disabled project: %s", project.get("sk"))
            continue

        project_sk = project["sk"]
        log_group = project.get("override_log_group") or global_config["source_log_group"]

        # Search start: last_searched_at or default window
        search_start = project.get("last_searched_at")
        if not search_start:
            default_start = search_end - timedelta(minutes=DEFAULT_SEARCH_WINDOW_MIN)
            search_start = default_start.strftime("%Y-%m-%dT%H:%M:%SZ")

        logger.info(
            "Processing project %s: log_group=%s, range=[%s, %s]",
            project_sk,
            log_group,
            search_start,
            search_end_iso,
        )

        monitors = project.get("monitors", [])

        for monitor in monitors:
            keyword = monitor["keyword"]
            results["total_monitors"] += 1

            # 2. Search logs
            raw_matches = filter_log_events_with_pagination(
                log_group=log_group,
                stream_prefix=project.get("stream_prefix"),
                keyword=keyword,
                start_time=search_start,
                end_time=search_end_iso,
            )

            # 3. Apply exclusion filters (PROJECT + MONITOR level)
            excludes = project.get("exclude_patterns", []) + monitor.get("exclude_patterns", [])
            matches = apply_exclusions_regex(raw_matches, excludes)

            results["total_detections"] += len(matches)

            # 4. Send metrics (always, even if 0, unless explicitly disabled)
            if not global_config.get("disable_custom_metrics", False):
                put_metric_data(
                    namespace=global_config.get("metric_namespace", "LogMonitor"),
                    project=project_sk,
                    keyword=keyword,
                    value=len(matches),
                )

            # 5. Evaluate state transition
            state = find_state(states, project_sk, keyword)
            action = evaluate_state(state, matches, monitor, global_config)

            logger.info(
                "Project %s, keyword %s: matches=%d, action=%s",
                project_sk,
                keyword,
                len(matches),
                action,
            )

            # 6. Send notification if needed
            if action in ("NOTIFY", "RENOTIFY", "RECOVER"):
                topic_arn = resolve_sns_topic(monitor, project, global_config)
                template = resolve_template(monitor, project, global_config)
                message = render_message(template, project, monitor, matches, action, global_config, state)
                sns_publish(topic_arn, message)
                results["notifications_sent"] += 1

            # 7. Update STATE in DynamoDB
            streak = (state.get("current_streak", 0) if state else 0) + 1 if len(matches) > 0 else 0

            if action == "NOTIFY":
                update_state(table, project_sk, keyword, "ALARM", search_end_iso, len(matches), streak)
            elif action == "RENOTIFY":
                update_state(table, project_sk, keyword, "ALARM", search_end_iso, len(matches), streak)
            elif action == "SUPPRESS":
                update_state_suppress(table, project_sk, keyword, len(matches), streak)
            elif action in ("RECOVER", "RECOVER_SILENT"):
                update_state(table, project_sk, keyword, "OK", search_end_iso)
            # NOOP: no state update needed

        # 8. Update project timestamp after all monitors processed
        update_project_timestamp(table, project_sk, search_end_iso)
        results["processed_projects"] += 1

    logger.info("Processing complete: %s", results)
    return results
