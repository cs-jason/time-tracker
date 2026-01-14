#!/usr/bin/env python3
"""Activity block aggregation utilities."""
from __future__ import annotations

from typing import Optional

from tt_db import DB_PATH, format_utc_timestamp, get_db_connection, parse_utc_timestamp
from tt_models import Activity


def update_activity_block(activity: Activity, db_path=DB_PATH) -> None:
    with get_db_connection(db_path) as conn:
        last = conn.execute(
            "SELECT id, start_time, end_time, app_name, bundle_id, window_title, file_path, url, idle "
            "FROM activity_blocks ORDER BY id DESC LIMIT 1"
        ).fetchone()

        if last and _block_matches(last, activity):
            new_end = format_utc_timestamp(activity.timestamp)
            start_dt = parse_utc_timestamp(last["start_time"])
            end_dt = parse_utc_timestamp(new_end)
            duration = round((end_dt - start_dt).total_seconds())
            conn.execute(
                "UPDATE activity_blocks SET end_time = ?, duration = ? WHERE id = ?",
                (new_end, duration, last["id"]),
            )
            return

        conn.execute(
            "INSERT INTO activity_blocks "
            "(start_time, end_time, duration, app_name, bundle_id, window_title, file_path, url, idle) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                format_utc_timestamp(activity.timestamp),
                format_utc_timestamp(activity.timestamp),
                0,
                activity.app_name,
                activity.bundle_id,
                activity.window_title,
                activity.file_path,
                activity.url,
                1 if activity.idle else 0,
            ),
        )


def _block_matches(last, activity: Activity) -> bool:
    def _eq(a: Optional[str], b: Optional[str]) -> bool:
        return a == b

    return (
        _eq(last["app_name"], activity.app_name)
        and _eq(last["bundle_id"], activity.bundle_id)
        and _eq(last["window_title"], activity.window_title)
        and _eq(last["file_path"], activity.file_path)
        and _eq(last["url"], activity.url)
        and int(last["idle"]) == (1 if activity.idle else 0)
    )
