"""Exclusion pattern filtering with regex support."""

import logging
import re

logger = logging.getLogger(__name__)


def apply_exclusions_regex(events, exclude_patterns):
    """Filter out log events that match any exclusion pattern.

    Patterns are treated as regular expressions. If a pattern is an invalid
    regex, it is logged and skipped safely.

    Args:
        events: List of CloudWatch log event dicts (must have "message" key).
        exclude_patterns: List of regex pattern strings.

    Returns:
        list[dict]: Events that do NOT match any exclusion pattern.
    """
    if not exclude_patterns:
        return events

    # Pre-compile patterns, skipping invalid ones
    compiled = []
    for pattern in exclude_patterns:
        try:
            compiled.append(re.compile(pattern))
        except re.error as e:
            logger.warning("Invalid exclusion regex pattern '%s': %s", pattern, e)

    if not compiled:
        return events

    filtered = []
    for event in events:
        message = event.get("message", "")
        if not any(regex.search(message) for regex in compiled):
            filtered.append(event)

    excluded_count = len(events) - len(filtered)
    if excluded_count > 0:
        logger.info("Excluded %d events out of %d by exclusion patterns", excluded_count, len(events))

    return filtered
