"""Select a single completed historical hour from a graph."""

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from math import isfinite
from typing import Any


@dataclass(frozen=True)
class Hour:
    """One hourly amount and its source position."""

    value: float
    timestamp: datetime
    index: int


def _amount(raw: Any) -> float | None:
    if isinstance(raw, bool) or not isinstance(raw, (int, float)):
        return None
    try:
        value = float(raw)
    except OverflowError:
        return None
    return value if isfinite(value) and value >= 0 else None


def _instant(raw: Any) -> datetime | None:
    try:
        if isinstance(raw, str):
            value = datetime.fromisoformat(raw.replace("Z", "+00:00"))
        elif isinstance(raw, (int, float)) and not isinstance(raw, bool):
            value = datetime.fromtimestamp(raw / 1000, timezone.utc)
        else:
            return None
    except (ValueError, OverflowError, OSError):
        return None
    return value if value.tzinfo is not None and value.utcoffset() is not None else None


def select_hour(slots: Any, now: datetime, lag: int) -> Hour | None:
    """Choose the hour ending lag hours ago, without inventing missing data."""
    if (
        not isinstance(slots, list)
        or now.tzinfo is None
        or now.utcoffset() is None
        or isinstance(lag, bool)
        or not isinstance(lag, int)
        or lag < 1
    ):
        return None
    target = (
        (now.astimezone(timezone.utc) - timedelta(hours=lag))
        .replace(minute=0, second=0, microsecond=0)
        .astimezone(now.tzinfo)
    )
    if slots and any(isinstance(slot, dict) for slot in slots):
        if not all(isinstance(slot, dict) for slot in slots):
            return None
        matches = [
            (index, slot)
            for index, slot in enumerate(slots)
            if (instant := _instant(slot.get("x"))) is not None
            and instant.astimezone(timezone.utc) == target.astimezone(timezone.utc)
        ]
        if len(matches) != 1:
            return None
        index, slot = matches[0]
        value = _amount(slot.get("y"))
        return Hour(value, target, index) if value is not None else None

    # Positional arrays are only safe when both local calendar days have 24 hours.
    today = now.date()
    yesterday = today - timedelta(days=1)
    midnight_yesterday = datetime.combine(yesterday, datetime.min.time(), now.tzinfo)
    midnight_today = datetime.combine(today, datetime.min.time(), now.tzinfo)
    midnight_tomorrow = datetime.combine(
        today + timedelta(days=1), datetime.min.time(), now.tzinfo
    )
    if (
        len(slots) != 48
        or (
            midnight_today.astimezone(timezone.utc)
            - midnight_yesterday.astimezone(timezone.utc)
        )
        != timedelta(hours=24)
        or (
            midnight_tomorrow.astimezone(timezone.utc)
            - midnight_today.astimezone(timezone.utc)
        )
        != timedelta(hours=24)
        or target.date() not in (yesterday, today)
    ):
        return None
    index = (0 if target.date() == yesterday else 24) + target.hour
    value = _amount(slots[index])
    return Hour(value, target, index) if value is not None else None


def utility_type(label: str) -> str | None:
    """Recognize only the utility types supported by this integration."""
    normalized = label.lower().replace("_", " ").replace("-", " ").strip()
    for key, tokens in (
        ("electricity", ("electric",)),
        ("cold_water", ("cold water",)),
        ("hot_water", ("hot water",)),
        ("cooling", ("cooling",)),
        ("heating", ("heating",)),
    ):
        if any(token in normalized for token in tokens):
            return key
    return None
