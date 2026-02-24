"""State transition logic for monitor alarms."""

import logging
from datetime import datetime, timezone

logger = logging.getLogger(__name__)


def find_state(states, project_sk, keyword):
    """Find the STATE record for a specific project+keyword combination.

    Args:
        states: List of all STATE records from DynamoDB.
        project_sk: Project sort key (e.g. "project-a").
        keyword: Monitor keyword (e.g. "ERROR").

    Returns:
        dict or None: Matching STATE record, or None if not found.
    """
    target_sk = f"{project_sk}#{keyword}"
    for state in states:
        if state.get("sk") == target_sk:
            return state
    return None


def _minutes_since(iso_timestamp):
    """Calculate minutes elapsed since the given ISO timestamp.

    Args:
        iso_timestamp: ISO 8601 timestamp string.

    Returns:
        float: Minutes elapsed since the timestamp.
    """
    dt = datetime.fromisoformat(iso_timestamp.replace("Z", "+00:00"))
    now = datetime.now(timezone.utc)
    return (now - dt).total_seconds() / 60


def evaluate_state(state, matches, monitor, global_config):
    """Determine the action to take based on current state and detection results.

    State transitions (DESIGN.md §6.3):
        - Detected + status=OK     → NOTIFY (new incident)
        - Detected + status=ALARM  → RENOTIFY (if renotify_min elapsed) or SUPPRESS
        - Not detected + status=ALARM → RECOVER or RECOVER_SILENT
        - Not detected + status=OK   → NOOP

    Args:
        state: Current STATE record (dict or None).
        matches: List of matching log events (after exclusion filtering).
        monitor: Monitor configuration dict.
        global_config: GLOBAL configuration dict.

    Returns:
        str: Action to take - one of:
            "NOTIFY", "RENOTIFY", "SUPPRESS", "RECOVER", "RECOVER_SILENT", "NOOP"
    """
    count = len(matches)
    status = state.get("status", "OK") if state else "OK"
    defaults = global_config.get("defaults", {})
    notify_on_recover = defaults.get("notify_on_recover", False)

    # Resolve renotify_min: MONITOR → GLOBAL defaults
    renotify = monitor.get("renotify_min")
    if renotify is None and "renotify_min" not in monitor:
        renotify = defaults.get("renotify_min")

    if count > 0:
        if status == "OK":
            return "NOTIFY"
        elif status == "ALARM":
            last_notified = state.get("last_notified_at") if state else None
            if last_notified and renotify and _minutes_since(last_notified) >= renotify:
                return "RENOTIFY"
            return "SUPPRESS"
    else:
        if status == "ALARM":
            return "RECOVER" if notify_on_recover else "RECOVER_SILENT"
        return "NOOP"
