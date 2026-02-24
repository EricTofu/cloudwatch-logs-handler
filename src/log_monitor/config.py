"""DynamoDB configuration reader for log-monitor table."""

import logging

import boto3

logger = logging.getLogger(__name__)

TABLE_NAME = "log-monitor"


def _get_table():
    """Get DynamoDB table resource."""
    dynamodb = boto3.resource("dynamodb")
    return dynamodb.Table(TABLE_NAME)


def get_global_config(table=None):
    """Retrieve the GLOBAL#CONFIG record from DynamoDB.

    Returns:
        dict: Global configuration record.

    Raises:
        KeyError: If GLOBAL#CONFIG record is not found.
    """
    table = table or _get_table()
    response = table.get_item(Key={"pk": "GLOBAL", "sk": "CONFIG"})
    item = response.get("Item")
    if not item:
        raise KeyError("GLOBAL#CONFIG record not found in DynamoDB")
    return item


def _query_all_by_pk(table, pk):
    """Query all records with the given partition key, handling pagination.

    Args:
        table: DynamoDB table resource.
        pk: Partition key value.

    Returns:
        list[dict]: All matching records.
    """
    items = []
    kwargs = {
        "KeyConditionExpression": boto3.dynamodb.conditions.Key("pk").eq(pk),
    }

    while True:
        response = table.query(**kwargs)
        items.extend(response.get("Items", []))

        last_key = response.get("LastEvaluatedKey")
        if not last_key:
            break
        kwargs["ExclusiveStartKey"] = last_key

    return items


def query_all_projects(table=None):
    """Retrieve all PROJECT records from DynamoDB.

    Returns:
        list[dict]: All project configuration records.
    """
    table = table or _get_table()
    return _query_all_by_pk(table, "PROJECT")


def query_all_states(table=None):
    """Retrieve all STATE records from DynamoDB.

    Returns:
        list[dict]: All state records.
    """
    table = table or _get_table()
    return _query_all_by_pk(table, "STATE")


def update_project_timestamp(table, project_sk, timestamp_iso):
    """Update the last_searched_at timestamp for a project.

    Args:
        table: DynamoDB table resource.
        project_sk: Sort key of the project.
        timestamp_iso: ISO 8601 timestamp string.
    """
    table.update_item(
        Key={"pk": "PROJECT", "sk": project_sk},
        UpdateExpression="SET last_searched_at = :ts",
        ExpressionAttributeValues={":ts": timestamp_iso},
    )


def update_state(table, project_sk, keyword, status, now_iso, detection_count=0, current_streak=0):
    """Create or update a STATE record in DynamoDB.

    Args:
        table: DynamoDB table resource.
        project_sk: Project sort key.
        keyword: Monitor keyword.
        status: New status ("ALARM" or "OK").
        now_iso: Current timestamp in ISO 8601.
        detection_count: Total detection count.
        current_streak: Current consecutive detection count.
    """
    sk = f"{project_sk}#{keyword}"

    if status == "ALARM":
        table.update_item(
            Key={"pk": "STATE", "sk": sk},
            UpdateExpression=(
                "SET #status = :status, "
                "last_detected_at = :now, "
                "last_notified_at = :now, "
                "detection_count = if_not_exists(detection_count, :zero) + :count, "
                "current_streak = :streak"
            ),
            ExpressionAttributeNames={"#status": "status"},
            ExpressionAttributeValues={
                ":status": status,
                ":now": now_iso,
                ":zero": 0,
                ":count": detection_count,
                ":streak": current_streak,
            },
        )
    elif status == "OK":
        table.update_item(
            Key={"pk": "STATE", "sk": sk},
            UpdateExpression="SET #status = :status, current_streak = :zero",
            ExpressionAttributeNames={"#status": "status"},
            ExpressionAttributeValues={
                ":status": status,
                ":zero": 0,
            },
        )


def update_state_suppress(table, project_sk, keyword, detection_count, current_streak):
    """Update STATE record for SUPPRESS action (detected but not notifying).

    Updates detection count and streak without changing last_notified_at.

    Args:
        table: DynamoDB table resource.
        project_sk: Project sort key.
        keyword: Monitor keyword.
        detection_count: Number of new detections.
        current_streak: New streak count.
    """
    sk = f"{project_sk}#{keyword}"
    table.update_item(
        Key={"pk": "STATE", "sk": sk},
        UpdateExpression=(
            "SET detection_count = if_not_exists(detection_count, :zero) + :count, current_streak = :streak"
        ),
        ExpressionAttributeValues={
            ":zero": 0,
            ":count": detection_count,
            ":streak": current_streak,
        },
    )
