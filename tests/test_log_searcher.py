"""Tests for log_searcher.py — CloudWatch Logs search."""

from unittest.mock import MagicMock

from log_monitor.log_searcher import filter_log_events_with_pagination, iso_to_epoch_ms


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
