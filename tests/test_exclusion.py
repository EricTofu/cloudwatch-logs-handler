"""Tests for exclusion.py — Exclusion pattern filtering."""

from log_monitor.exclusion import apply_exclusions_regex


class TestApplyExclusionsRegex:
    def _make_events(self, messages):
        return [{"message": m, "logStreamName": "s1", "timestamp": i} for i, m in enumerate(messages)]

    def test_no_patterns_returns_all(self):
        events = self._make_events(["ERROR: foo", "ERROR: bar"])
        result = apply_exclusions_regex(events, [])
        assert len(result) == 2

    def test_none_patterns_returns_all(self):
        events = self._make_events(["ERROR: foo"])
        result = apply_exclusions_regex(events, None)
        assert len(result) == 1

    def test_simple_string_exclusion(self):
        events = self._make_events(
            [
                "ERROR: database connection failed",
                "ERROR: connection reset by peer",
                "ERROR: out of memory",
            ]
        )
        result = apply_exclusions_regex(events, ["connection reset"])
        assert len(result) == 2
        assert all("connection reset" not in e["message"] for e in result)

    def test_regex_pattern_exclusion(self):
        events = self._make_events(
            [
                "ERROR: database connection failed",
                "ERROR during healthcheck handler",
                "ERROR: timeout after 30s",
            ]
        )
        result = apply_exclusions_regex(events, [r"healthcheck\s+handler"])
        assert len(result) == 2

    def test_multiple_patterns(self):
        events = self._make_events(
            [
                "ERROR: database connection failed",
                "ERROR: connection reset by peer",
                "ERROR during healthcheck handler",
                "ERROR: out of memory",
            ]
        )
        result = apply_exclusions_regex(events, ["connection reset", "healthcheck"])
        assert len(result) == 2
        messages = [e["message"] for e in result]
        assert "ERROR: database connection failed" in messages
        assert "ERROR: out of memory" in messages

    def test_invalid_regex_pattern_skipped(self):
        events = self._make_events(["ERROR: foo", "ERROR: bar"])
        # Invalid regex (unmatched bracket) should be skipped
        result = apply_exclusions_regex(events, ["[invalid"])
        assert len(result) == 2

    def test_mixed_valid_and_invalid_patterns(self):
        events = self._make_events(["ERROR: foo bar", "ERROR: baz"])
        result = apply_exclusions_regex(events, ["[invalid", "foo bar"])
        assert len(result) == 1
        assert result[0]["message"] == "ERROR: baz"

    def test_empty_events_list(self):
        result = apply_exclusions_regex([], ["pattern"])
        assert result == []

    def test_all_excluded(self):
        events = self._make_events(["ERROR: cache miss", "ERROR: cache miss again"])
        result = apply_exclusions_regex(events, ["cache miss"])
        assert len(result) == 0
