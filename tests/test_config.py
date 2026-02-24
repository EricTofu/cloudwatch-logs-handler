"""Tests for config.py — DynamoDB configuration management."""

import pytest

from log_monitor.config import (
    get_global_config,
    query_all_projects,
    query_all_states,
    update_project_timestamp,
    update_state,
    update_state_suppress,
)


class TestGetGlobalConfig:
    def test_returns_global_config(self, dynamodb_table, global_config_item):
        dynamodb_table.put_item(Item=global_config_item)
        result = get_global_config(dynamodb_table)
        assert result["pk"] == "GLOBAL"
        assert result["sk"] == "CONFIG"
        assert result["source_log_group"] == "/aws/app/shared-logs"

    def test_raises_key_error_when_not_found(self, dynamodb_table):
        with pytest.raises(KeyError, match="GLOBAL#CONFIG"):
            get_global_config(dynamodb_table)


class TestQueryAllProjects:
    def test_returns_all_projects(self, dynamodb_table, project_a_item, project_b_item):
        dynamodb_table.put_item(Item=project_a_item)
        dynamodb_table.put_item(Item=project_b_item)
        result = query_all_projects(dynamodb_table)
        assert len(result) == 2
        sks = {p["sk"] for p in result}
        assert sks == {"project-a", "project-b"}

    def test_returns_empty_list_when_no_projects(self, dynamodb_table):
        result = query_all_projects(dynamodb_table)
        assert result == []


class TestQueryAllStates:
    def test_returns_all_states(self, dynamodb_table):
        dynamodb_table.put_item(Item={"pk": "STATE", "sk": "project-a#ERROR", "status": "ALARM"})
        dynamodb_table.put_item(Item={"pk": "STATE", "sk": "project-a#TIMEOUT", "status": "OK"})
        result = query_all_states(dynamodb_table)
        assert len(result) == 2

    def test_returns_empty_list_when_no_states(self, dynamodb_table):
        result = query_all_states(dynamodb_table)
        assert result == []


class TestUpdateProjectTimestamp:
    def test_updates_last_searched_at(self, dynamodb_table, project_a_item):
        dynamodb_table.put_item(Item=project_a_item)
        update_project_timestamp(dynamodb_table, "project-a", "2026-02-20T06:00:00Z")
        result = dynamodb_table.get_item(Key={"pk": "PROJECT", "sk": "project-a"})["Item"]
        assert result["last_searched_at"] == "2026-02-20T06:00:00Z"


class TestUpdateState:
    def test_creates_alarm_state(self, dynamodb_table):
        update_state(dynamodb_table, "project-a", "ERROR", "ALARM", "2026-02-20T05:10:00Z", 3, 1)
        result = dynamodb_table.get_item(Key={"pk": "STATE", "sk": "project-a#ERROR"})["Item"]
        assert result["status"] == "ALARM"
        assert result["last_detected_at"] == "2026-02-20T05:10:00Z"
        assert result["last_notified_at"] == "2026-02-20T05:10:00Z"
        assert result["current_streak"] == 1

    def test_updates_to_ok_state(self, dynamodb_table):
        # First create ALARM state
        update_state(dynamodb_table, "project-a", "ERROR", "ALARM", "2026-02-20T05:10:00Z", 3, 1)
        # Then recover
        update_state(dynamodb_table, "project-a", "ERROR", "OK", "2026-02-20T06:00:00Z")
        result = dynamodb_table.get_item(Key={"pk": "STATE", "sk": "project-a#ERROR"})["Item"]
        assert result["status"] == "OK"
        assert result["current_streak"] == 0


class TestUpdateStateSuppress:
    def test_updates_count_and_streak_without_notified_at(self, dynamodb_table):
        # Create initial state
        update_state(dynamodb_table, "project-a", "ERROR", "ALARM", "2026-02-20T05:10:00Z", 3, 1)
        original = dynamodb_table.get_item(Key={"pk": "STATE", "sk": "project-a#ERROR"})["Item"]

        # Suppress — should not update last_notified_at
        update_state_suppress(dynamodb_table, "project-a", "ERROR", 2, 2)
        result = dynamodb_table.get_item(Key={"pk": "STATE", "sk": "project-a#ERROR"})["Item"]
        assert result["current_streak"] == 2
        assert result["last_notified_at"] == original["last_notified_at"]
