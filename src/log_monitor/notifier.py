"""SNS notification with 3-level fallback resolution and template rendering."""

import json
import logging
from datetime import datetime

import boto3

from log_monitor.constants import JST

logger = logging.getLogger(__name__)

# SNS message size limit (256 KB)
_SNS_MAX_MESSAGE_BYTES = 256 * 1024


def resolve_sns_topic(monitor, project, global_config):
    """Resolve SNS topic ARN using 3-level fallback.

    Priority (high → low):
        1. MONITOR override_sns_topic
        2. PROJECT override_sns_topics[severity]
        3. GLOBAL sns_topics[severity]

    Args:
        monitor: Monitor configuration dict.
        project: Project configuration dict.
        global_config: GLOBAL configuration dict.

    Returns:
        str: SNS topic ARN.
    """
    severity = monitor.get("severity") or global_config["defaults"]["severity"]

    # 1. MONITOR-level override
    if monitor.get("override_sns_topic"):
        return monitor["override_sns_topic"]

    # 2. PROJECT-level override
    project_topics = project.get("override_sns_topics", {})
    if severity in project_topics:
        return project_topics[severity]

    # 3. GLOBAL default
    return global_config["sns_topics"][severity]


def resolve_template(monitor, project, global_config):
    """Resolve notification template using 3-level fallback.

    Priority (high → low):
        1. MONITOR notification_template
        2. PROJECT notification_template
        3. GLOBAL notification_template

    Args:
        monitor: Monitor configuration dict.
        project: Project configuration dict.
        global_config: GLOBAL configuration dict.

    Returns:
        dict: Template dict with "subject" and "body" keys.
    """
    return (
        monitor.get("notification_template")
        or project.get("notification_template")
        or global_config["notification_template"]
    )


def render_message(template, project, monitor, matches, action, global_config, state=None, previous_log_lines=None):
    """Render notification message by expanding template variables.

    Template variables:
        {project}, {keyword}, {severity}, {count}, {detected_at},
        {log_group}, {stream_name}, {log_lines}, {streak}

    Args:
        template: Template dict with "subject". "body" is ignored and hardcoded.
        project: Project configuration dict.
        monitor: Monitor configuration dict.
        matches: List of matching log events.
        action: Action string (NOTIFY, RENOTIFY, RECOVER).
        global_config: GLOBAL configuration dict.
        state: Current STATE record (optional).
        previous_log_lines: List of previous log lines (optional).

    Returns:
        dict: Rendered message with "subject" and "body" keys.
    """
    now_jst = datetime.now(JST)

    # Use the timestamp of the latest matched log event if available, otherwise fallback to current time
    if matches and "timestamp" in matches[-1]:
        dt = datetime.fromtimestamp(matches[-1]["timestamp"] / 1000.0, tz=JST)
        detected_at_str = dt.strftime("%Y-%m-%d %H:%M:%S JST")
    else:
        detected_at_str = now_jst.strftime("%Y-%m-%d %H:%M:%S JST")

    severity = (monitor.get("severity") or global_config["defaults"]["severity"]).upper()
    log_group = project.get("override_log_group") or global_config.get("source_log_group", "")
    max_lines = int(global_config.get("max_log_lines", 20))

    # Extract stream names and log lines from matches
    stream_names = sorted(set(e.get("logStreamName", "") for e in matches)) if matches else []
    
    # Deduplicate burst log messages
    ordered_logs = []
    log_counts = {}
    for e in matches:
        msg = e.get("message", "").rstrip()
        if msg not in log_counts:
            ordered_logs.append(msg)
            log_counts[msg] = 0
        log_counts[msg] += 1

    formatted_lines = []
    for msg in ordered_logs[:max_lines]:
        count = log_counts[msg]
        if count > 1:
            formatted_lines.append(f"{msg} (x{count})")
        else:
            formatted_lines.append(msg)

    log_lines = "\n".join(formatted_lines)

    # Extract previous log lines
    prev_logs_text = "(なし)"
    if previous_log_lines:
        prev_logs_text = "\n".join(previous_log_lines)

    streak = 0
    if state:
        streak = state.get("current_streak", 0)

    # Optional mention
    mention = monitor.get("mention") or project.get("mention") or ""

    variables = {
        "project": project.get("display_name", project.get("sk", "")),
        "keyword": monitor.get("keyword", ""),
        "severity": severity,
        "count": str(len(matches)),
        "detected_at": detected_at_str,
        "log_group": log_group,
        "stream_name": ", ".join(stream_names),
        "log_lines": log_lines if log_lines else "(ログなし)",
        "streak": str(streak),
    }

    # Subject is templated
    # Use action-specific template adjustments for RECOVER
    if action == "RECOVER":
        subject = template.get("subject", "").replace("{severity}", "RECOVER")
        body = f"{variables['project']} の {variables['keyword']} が復旧しました\n{variables['detected_at']}"
    else:
        subject = template.get("subject", "")
        # Expand subject
        for key, value in variables.items():
            subject = subject.replace(f"{{{key}}}", value)

        # Hardcoded required format
        body_parts = [subject]
        if mention:
            body_parts.append(mention)

        body_parts.extend(
            [
                f"検出件数: {variables['count']}",
                f"タイムスタンプ: {variables['detected_at']}",
                f"ロググループ: {variables['log_group']}",
                f"ログストリーム: {variables['stream_name']}",
                "検出したログ本文:",
                variables["log_lines"],
                "検出したログ前のログ:",
                prev_logs_text,
            ]
        )
        body = "\n".join(body_parts)

    # Expand template variables for RECOVER subject
    if action == "RECOVER":
        for key, value in variables.items():
            subject = subject.replace(f"{{{key}}}", value)

    return {"subject": subject, "body": body}


def sns_publish(topic_arn, message, client=None):
    """Publish a notification message to an SNS topic.

    Args:
        topic_arn: SNS topic ARN.
        message: Dict with "subject" and "body" keys.
        client: Optional boto3 SNS client (for testing).
    """
    client = client or boto3.client("sns")

    body = message["body"]

    # Format for AWS Chatbot custom notification schema
    chatbot_payload = {
        "version": "1.0",
        "source": "custom",
        "content": {
            "title": message["subject"][:100],  # Max 100 characters for title
            "description": body,
        },
    }

    payload_str = json.dumps(chatbot_payload)

    # Truncate if payload exceeds SNS 256KB limit
    if len(payload_str.encode("utf-8")) > _SNS_MAX_MESSAGE_BYTES:
        max_body_bytes = _SNS_MAX_MESSAGE_BYTES - 1024  # Reserve space for JSON envelope
        truncated_body = body.encode("utf-8")[:max_body_bytes].decode("utf-8", errors="ignore")
        truncated_body += "\n... (truncated)"
        chatbot_payload["content"]["description"] = truncated_body
        payload_str = json.dumps(chatbot_payload)
        logger.warning("SNS message truncated for topic %s (exceeded 256KB)", topic_arn)

    try:
        client.publish(
            TopicArn=topic_arn,
            Subject=message["subject"][:100],  # SNS subject limit
            Message=payload_str,
        )
        logger.info("Published notification to %s: %s", topic_arn, message["subject"])
    except Exception:
        logger.exception("Failed to publish to SNS topic %s", topic_arn)
        raise
