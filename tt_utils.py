#!/usr/bin/env python3
"""Utility helpers for time and formatting."""
from __future__ import annotations

from datetime import date, datetime, time, timedelta, timezone
from typing import Optional, Tuple
from zoneinfo import ZoneInfo

from tt_db import format_utc_timestamp, parse_utc_timestamp


def local_tz() -> ZoneInfo:
    return datetime.now().astimezone().tzinfo  # type: ignore[return-value]


def parse_local_date(value: str) -> date:
    return date.fromisoformat(value)


def local_day_bounds(day: date) -> Tuple[datetime, datetime]:
    tz = local_tz()
    start_local = datetime.combine(day, time.min).replace(tzinfo=tz)
    end_local = start_local + timedelta(days=1) - timedelta(seconds=1)
    return start_local.astimezone(timezone.utc), end_local.astimezone(timezone.utc)


def local_range_from_strings(from_str: Optional[str], to_str: Optional[str]) -> Tuple[datetime, datetime]:
    if from_str is None or to_str is None:
        raise ValueError("from/to required")
    start = parse_local_date(from_str)
    end = parse_local_date(to_str)
    return local_day_bounds(start)[0], local_day_bounds(end)[1]


def format_local_timestamp(ts_utc: str) -> str:
    dt = parse_utc_timestamp(ts_utc)
    return dt.astimezone(local_tz()).strftime("%Y-%m-%d %H:%M:%S")


def format_local_date_range(start_utc: datetime, end_utc: datetime) -> str:
    tz = local_tz()
    start_local = start_utc.astimezone(tz)
    end_local = end_utc.astimezone(tz)
    if start_local.date() == end_local.date():
        return start_local.strftime("%B %-d, %Y")
    return f"{start_local.strftime('%B %-d')} - {end_local.strftime('%B %-d, %Y')}"


def human_duration(seconds: float) -> str:
    total = int(round(seconds))
    if total < 0:
        total = 0
    hours, remainder = divmod(total, 3600)
    minutes, secs = divmod(remainder, 60)
    return f"{hours:02d}:{minutes:02d}:{secs:02d}"


def human_duration_short(seconds: float) -> str:
    total = int(round(seconds))
    if total < 0:
        total = 0
    hours, remainder = divmod(total, 3600)
    minutes, secs = divmod(remainder, 60)
    parts = []
    if hours:
        parts.append(f"{hours}h")
    if minutes:
        parts.append(f"{minutes}m")
    if secs or not parts:
        parts.append(f"{secs}s")
    return " ".join(parts)


def utc_range_to_strings(start_utc: datetime, end_utc: datetime) -> Tuple[str, str]:
    return format_utc_timestamp(start_utc), format_utc_timestamp(end_utc)
