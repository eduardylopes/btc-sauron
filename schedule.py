"""Scheduling rules for daily reports."""
from __future__ import annotations

from datetime import datetime, timedelta


class DailySchedule:
    """Finds the next local occurrence of a configured daily time."""

    def __init__(self, report_time: str) -> None:
        try:
            hours, minutes = (int(value) for value in report_time.split(":", 1))
        except ValueError as error:
            raise ValueError("report_time must use HH:MM") from error
        if not 0 <= hours <= 23 or not 0 <= minutes <= 59:
            raise ValueError("report_time must use HH:MM")
        self._hours = hours
        self._minutes = minutes

    def next_after(self, now: datetime) -> datetime:
        candidate = now.replace(
            hour=self._hours, minute=self._minutes, second=0, microsecond=0
        )
        return candidate + timedelta(days=1) if candidate <= now else candidate
