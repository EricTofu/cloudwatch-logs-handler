"""Tests for state.py — State transition logic."""

from unittest.mock import patch

from log_monitor.state import evaluate_state, find_state


class TestFindState:
    def test_finds_matching_state(self):
        states = [
            {"sk": "project-a#ERROR", "status": "ALARM"},
            {"sk": "project-a#TIMEOUT", "status": "OK"},
        ]
        result = find_state(states, "project-a", "ERROR")
        assert result["status"] == "ALARM"

    def test_returns_none_when_not_found(self):
        states = [{"sk": "project-a#ERROR", "status": "ALARM"}]
        result = find_state(states, "project-b", "ERROR")
        assert result is None

    def test_empty_states_list(self):
        result = find_state([], "project-a", "ERROR")
        assert result is None


class TestEvaluateState:
    """Test all 6 state transitions from DESIGN.md §6.3."""

    GLOBAL_CONFIG = {
        "defaults": {
            "severity": "warning",
            "renotify_min": 60,
            "notify_on_recover": True,
        },
    }

    MONITOR = {"keyword": "ERROR", "severity": "critical"}

    def _make_matches(self, count):
        return [{"message": f"ERROR: msg {i}"} for i in range(count)]

    def test_notify_new_incident(self):
        """Detected + status=OK → NOTIFY"""
        result = evaluate_state(
            state=None,
            matches=self._make_matches(3),
            monitor=self.MONITOR,
            global_config=self.GLOBAL_CONFIG,
        )
        assert result == "NOTIFY"

    def test_notify_existing_ok_state(self):
        """Detected + status=OK (explicit state) → NOTIFY"""
        state = {"sk": "project-a#ERROR", "status": "OK"}
        result = evaluate_state(
            state=state,
            matches=self._make_matches(1),
            monitor=self.MONITOR,
            global_config=self.GLOBAL_CONFIG,
        )
        assert result == "NOTIFY"

    @patch("log_monitor.state._minutes_since")
    def test_renotify_after_interval(self, mock_minutes):
        """Detected + status=ALARM + renotify_min elapsed → RENOTIFY"""
        mock_minutes.return_value = 61  # More than 60 min
        state = {
            "sk": "project-a#ERROR",
            "status": "ALARM",
            "last_notified_at": "2026-02-20T04:00:00Z",
        }
        result = evaluate_state(
            state=state,
            matches=self._make_matches(2),
            monitor=self.MONITOR,
            global_config=self.GLOBAL_CONFIG,
        )
        assert result == "RENOTIFY"

    @patch("log_monitor.state._minutes_since")
    def test_suppress_within_interval(self, mock_minutes):
        """Detected + status=ALARM + renotify_min NOT elapsed → SUPPRESS"""
        mock_minutes.return_value = 30  # Less than 60 min
        state = {
            "sk": "project-a#ERROR",
            "status": "ALARM",
            "last_notified_at": "2026-02-20T04:40:00Z",
        }
        result = evaluate_state(
            state=state,
            matches=self._make_matches(1),
            monitor=self.MONITOR,
            global_config=self.GLOBAL_CONFIG,
        )
        assert result == "SUPPRESS"

    def test_suppress_renotify_null(self):
        """Detected + status=ALARM + renotify_min=null → SUPPRESS (no re-notify)"""
        state = {
            "sk": "project-a#ERROR",
            "status": "ALARM",
            "last_notified_at": "2026-02-20T04:00:00Z",
        }
        monitor = {"keyword": "TIMEOUT", "severity": "warning", "renotify_min": None}
        result = evaluate_state(
            state=state,
            matches=self._make_matches(1),
            monitor=monitor,
            global_config=self.GLOBAL_CONFIG,
        )
        assert result == "SUPPRESS"

    def test_recover_with_notification(self):
        """Not detected + status=ALARM + notify_on_recover=true → RECOVER"""
        state = {"sk": "project-a#ERROR", "status": "ALARM"}
        result = evaluate_state(
            state=state,
            matches=[],
            monitor=self.MONITOR,
            global_config=self.GLOBAL_CONFIG,
        )
        assert result == "RECOVER"

    def test_recover_silent(self):
        """Not detected + status=ALARM + notify_on_recover=false → RECOVER_SILENT"""
        state = {"sk": "project-a#ERROR", "status": "ALARM"}
        config = {
            "defaults": {
                "severity": "warning",
                "renotify_min": 60,
                "notify_on_recover": False,
            },
        }
        result = evaluate_state(
            state=state,
            matches=[],
            monitor=self.MONITOR,
            global_config=config,
        )
        assert result == "RECOVER_SILENT"

    def test_noop(self):
        """Not detected + status=OK → NOOP"""
        result = evaluate_state(
            state=None,
            matches=[],
            monitor=self.MONITOR,
            global_config=self.GLOBAL_CONFIG,
        )
        assert result == "NOOP"

    def test_noop_explicit_ok_state(self):
        """Not detected + explicit status=OK → NOOP"""
        state = {"sk": "project-a#ERROR", "status": "OK"}
        result = evaluate_state(
            state=state,
            matches=[],
            monitor=self.MONITOR,
            global_config=self.GLOBAL_CONFIG,
        )
        assert result == "NOOP"

    def test_renotify_min_fallback_to_global(self):
        """Monitor without renotify_min should use GLOBAL default."""
        monitor_no_renotify = {"keyword": "ERROR", "severity": "critical"}
        state = {
            "sk": "project-a#ERROR",
            "status": "ALARM",
            "last_notified_at": "2026-02-20T04:00:00Z",
        }
        with patch("log_monitor.state._minutes_since", return_value=61):
            result = evaluate_state(
                state=state,
                matches=self._make_matches(1),
                monitor=monitor_no_renotify,
                global_config=self.GLOBAL_CONFIG,
            )
        assert result == "RENOTIFY"
