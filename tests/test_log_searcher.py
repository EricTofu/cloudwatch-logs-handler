"""Tests for log_searcher.py — CloudWatch Logs search."""

from unittest.mock import MagicMock

from log_monitor.log_searcher import filter_log_events_with_pagination, get_previous_log_lines, iso_to_epoch_ms


class TestIsoToEpochMs:
    def test_utc_timestamp(self):
        result = iso_to_epoch_ms("2026-02-20T05:10:00Z")
        from datetime import datetime, timezone

        expected = int(datetime(2026, 2, 20, 5, 10, tzinfo=timezone.utc).timestamp() * 1000)
        assert result == expected

    def test_timezone_offset(self):
        result = iso_to_epoch_ms("2026-02-20T14:10:00+09:00")
        from datetime import datetime, timezone

        expected = int(datetime(2026, 2, 20, 5, 10, tzinfo=timezone.utc).timestamp() * 1000)
        assert result == expected


class TestFilterLogEventsWithPagination:
    def test_single_page(self):
        mock_client = MagicMock()
        mock_client.filter_log_events.return_value = {
            "events": [
                {"message": "ERROR: something failed", "logStreamName": "project-a/stream-1", "timestamp": 1000},
                {"message": "ERROR: another issue", "logStreamName": "project-a/stream-1", "timestamp": 2000},
            ],
        }

        result = filter_log_events_with_pagination(
            log_group="/aws/app/shared-logs",
            stream_prefix="project-a",
            keyword="ERROR",
            start_time="2026-02-20T05:00:00Z",
            end_time="2026-02-20T05:10:00Z",
            client=mock_client,
        )

        assert len(result) == 2
        mock_client.filter_log_events.assert_called_once()
        call_kwargs = mock_client.filter_log_events.call_args[1]
        assert call_kwargs["logGroupName"] == "/aws/app/shared-logs"
        assert call_kwargs["logStreamNamePrefix"] == "project-a"
        assert call_kwargs["filterPattern"] == '"ERROR"'

    def test_pagination(self):
        mock_client = MagicMock()
        mock_client.filter_log_events.side_effect = [
            {
                "events": [{"message": "ERROR: page 1", "logStreamName": "s1", "timestamp": 1000}],
                "nextToken": "token-1",
            },
            {
                "events": [{"message": "ERROR: page 2", "logStreamName": "s1", "timestamp": 2000}],
            },
        ]

        result = filter_log_events_with_pagination(
            log_group="/aws/app/shared-logs",
            stream_prefix="project-a",
            keyword="ERROR",
            start_time="2026-02-20T05:00:00Z",
            end_time="2026-02-20T05:10:00Z",
            client=mock_client,
        )

        assert len(result) == 2
        assert mock_client.filter_log_events.call_count == 2

    def test_no_stream_prefix(self):
        mock_client = MagicMock()
        mock_client.filter_log_events.return_value = {"events": []}

        filter_log_events_with_pagination(
            log_group="/aws/app/project-a",
            stream_prefix=None,
            keyword="ERROR",
            start_time="2026-02-20T05:00:00Z",
            end_time="2026-02-20T05:10:00Z",
            client=mock_client,
        )

        call_kwargs = mock_client.filter_log_events.call_args[1]
        assert "logStreamNamePrefix" not in call_kwargs

    def test_empty_results(self):
        mock_client = MagicMock()
        mock_client.filter_log_events.return_value = {"events": []}

        result = filter_log_events_with_pagination(
            log_group="/aws/app/shared-logs",
            stream_prefix="project-a",
            keyword="ERROR",
            start_time="2026-02-20T05:00:00Z",
            end_time="2026-02-20T05:10:00Z",
            client=mock_client,
        )

        assert result == []


class TestGetPreviousLogLines:
    def test_returns_lines_before_target(self):
        """Basic: lines before the exact target timestamp are returned."""
        mock_client = MagicMock()
        mock_client.get_log_events.side_effect = [
            {
                "events": [
                    {"message": "INFO: starting up\n", "timestamp": 1000},
                    {"message": "INFO: connected\n", "timestamp": 2000},
                    {"message": "ERROR: db failed\n", "timestamp": 3000},
                ],
                "nextForwardToken": "token-1",
            },
            {
                "events": [],
                "nextForwardToken": "token-1",
            },
        ]

        result = get_previous_log_lines(
            log_group="/aws/app/shared-logs",
            stream_name="project-a/s1",
            timestamp=3000,
            limit=5,
            match_message="ERROR: db failed\n",
            client=mock_client,
        )

        assert result == ["INFO: starting up", "INFO: connected"]

    def test_same_timestamp_burst_with_match_message(self):
        """Multiple events at the same timestamp — only cut at matching message."""
        mock_client = MagicMock()
        mock_client.get_log_events.side_effect = [
            {
                "events": [
                    {"message": "INFO: step 1\n", "timestamp": 1000},
                    {"message": "INFO: step 2\n", "timestamp": 2000},
                    {"message": "ERROR: first\n", "timestamp": 3000},
                    {"message": "ERROR: second\n", "timestamp": 3000},
                ],
                "nextForwardToken": "token-1",
            },
            {
                "events": [],
                "nextForwardToken": "token-1",
            },
        ]

        # Should find "ERROR: second" (last match scanning backward) and return everything before it
        result = get_previous_log_lines(
            log_group="/aws/app/shared-logs",
            stream_name="project-a/s1",
            timestamp=3000,
            limit=5,
            match_message="ERROR: second\n",
            client=mock_client,
        )

        assert result == ["INFO: step 1", "INFO: step 2", "ERROR: first"]

    def test_fallback_when_target_not_found(self):
        """If exact match is not found, fall back to timestamp-based filter."""
        mock_client = MagicMock()
        mock_client.get_log_events.side_effect = [
            {
                "events": [
                    {"message": "INFO: before\n", "timestamp": 1000},
                    {"message": "ERROR: different msg\n", "timestamp": 3000},
                ],
                "nextForwardToken": "token-1",
            },
            {
                "events": [],
                "nextForwardToken": "token-1",
            },
        ]

        result = get_previous_log_lines(
            log_group="/aws/app/shared-logs",
            stream_name="project-a/s1",
            timestamp=3000,
            limit=5,
            match_message="ERROR: nonexistent\n",
            client=mock_client,
        )

        # Fallback: only events strictly before timestamp=3000
        assert result == ["INFO: before"]

    def test_respects_limit(self):
        """Only the last `limit` lines are returned."""
        mock_client = MagicMock()
        mock_client.get_log_events.side_effect = [
            {
                "events": [
                    {"message": "line 1\n", "timestamp": 1000},
                    {"message": "line 2\n", "timestamp": 2000},
                    {"message": "line 3\n", "timestamp": 3000},
                    {"message": "ERROR\n", "timestamp": 4000},
                ],
                "nextForwardToken": "token-1",
            },
            {
                "events": [],
                "nextForwardToken": "token-1",
            },
        ]

        result = get_previous_log_lines(
            log_group="/aws/app/shared-logs",
            stream_name="project-a/s1",
            timestamp=4000,
            limit=2,
            client=mock_client,
        )

        assert result == ["line 2", "line 3"]

    def test_zero_limit_returns_empty(self):
        result = get_previous_log_lines(
            log_group="/aws/app/shared-logs",
            stream_name="project-a/s1",
            timestamp=1000,
            limit=0,
        )
        assert result == []

    def test_empty_stream_name_returns_empty(self):
        result = get_previous_log_lines(
            log_group="/aws/app/shared-logs",
            stream_name="",
            timestamp=1000,
            limit=5,
        )
        assert result == []

    def test_exception_returns_empty(self):
        """API errors are caught and return empty list."""
        mock_client = MagicMock()
        mock_client.get_log_events.side_effect = Exception("API error")

        result = get_previous_log_lines(
            log_group="/aws/app/shared-logs",
            stream_name="project-a/s1",
            timestamp=3000,
            limit=5,
            client=mock_client,
        )

        assert result == []

    def test_pagination(self):
        """Results spanning multiple pages are collected correctly."""
        mock_client = MagicMock()
        mock_client.get_log_events.side_effect = [
            {
                "events": [
                    {"message": "INFO: page 1\n", "timestamp": 1000},
                ],
                "nextForwardToken": "token-2",
            },
            {
                "events": [
                    {"message": "INFO: page 2\n", "timestamp": 2000},
                    {"message": "ERROR: target\n", "timestamp": 3000},
                ],
                "nextForwardToken": "token-2",  # Same token = no more data
            },
        ]

        result = get_previous_log_lines(
            log_group="/aws/app/shared-logs",
            stream_name="project-a/s1",
            timestamp=3000,
            limit=5,
            match_message="ERROR: target\n",
            client=mock_client,
        )

        assert result == ["INFO: page 1", "INFO: page 2"]
        assert mock_client.get_log_events.call_count == 2
