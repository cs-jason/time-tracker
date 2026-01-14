#!/usr/bin/env python3
"""Session tracking logic (non-OS specific)."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Optional

from tt_db import DB_PATH, Config, format_utc_timestamp, get_db_connection
from tt_models import Activity
from tt_rules import MatchResult, RuleEngine


@dataclass
class SessionState:
    project_id: int
    start_time: datetime
    triggered_by: str
    duration_seconds: float
    last_active_time: datetime
    last_tracked_time: Optional[datetime]


class SessionManager:
    def __init__(self, config: Config, db_path=DB_PATH):
        self.config = config
        self.db_path = db_path
        self.rule_engine = RuleEngine(db_path)
        self.current_session: Optional[SessionState] = None

    def update_config(self, config: Config) -> None:
        self.config = config

    def reload_rules(self) -> None:
        self.rule_engine.reload()

    def process_activity(self, activity: Activity) -> None:
        if self.config.tracking_paused:
            match = None
        else:
            match = self._match_activity(activity)

        if match is None:
            self._handle_inactive(activity)
        else:
            self._handle_active(activity, match)

    def _match_activity(self, activity: Activity) -> Optional[MatchResult]:
        if activity.idle:
            return None
        return self.rule_engine.match(activity)

    def _handle_active(self, activity: Activity, match: MatchResult) -> None:
        if self.current_session is None:
            self.current_session = SessionState(
                project_id=match.project_id,
                start_time=activity.timestamp,
                triggered_by=match.triggered_by,
                duration_seconds=0.0,
                last_active_time=activity.timestamp,
                last_tracked_time=activity.timestamp,
            )
            return

        if self.current_session.project_id != match.project_id:
            # Close previous session at last active time.
            self._end_session(self.current_session.last_active_time)
            self.current_session = SessionState(
                project_id=match.project_id,
                start_time=activity.timestamp,
                triggered_by=match.triggered_by,
                duration_seconds=0.0,
                last_active_time=activity.timestamp,
                last_tracked_time=activity.timestamp,
            )
            return

        # Same project: accumulate time between active samples.
        if self.current_session.last_tracked_time is not None:
            delta = (activity.timestamp - self.current_session.last_tracked_time).total_seconds()
            if delta > 0:
                self.current_session.duration_seconds += delta
        self.current_session.last_tracked_time = activity.timestamp
        self.current_session.last_active_time = activity.timestamp
        self.current_session.triggered_by = match.triggered_by

    def _handle_inactive(self, activity: Activity) -> None:
        if self.current_session is None:
            return

        # Pause duration accumulation during idle/non-match gaps.
        self.current_session.last_tracked_time = None

        grace = (
            self.config.idle_grace_period if activity.idle else self.config.session_grace_period
        )
        elapsed = (activity.timestamp - self.current_session.last_active_time).total_seconds()
        if elapsed > grace:
            self._end_session(self.current_session.last_active_time)
            self.current_session = None

    def current_duration(self, now: datetime) -> Optional[int]:
        if self.current_session is None:
            return None
        duration = self.current_session.duration_seconds
        if self.current_session.last_tracked_time is not None:
            delta = (now - self.current_session.last_tracked_time).total_seconds()
            if delta > 0:
                duration += delta
        return int(round(duration))

    def pause(self, end_time: Optional[datetime] = None) -> None:
        if self.current_session is None:
            return
        end_time = end_time or self.current_session.last_active_time
        self._end_session(end_time)
        self.current_session = None

    def _end_session(self, end_time: datetime) -> None:
        if self.current_session is None:
            return
        duration = round(self.current_session.duration_seconds)
        if duration < self.config.min_session_duration:
            self.current_session = None
            return
        with get_db_connection(self.db_path) as conn:
            conn.execute(
                "INSERT INTO sessions (project_id, start_time, end_time, duration, triggered_by) "
                "VALUES (?, ?, ?, ?, ?)",
                (
                    self.current_session.project_id,
                    format_utc_timestamp(self.current_session.start_time),
                    format_utc_timestamp(end_time),
                    duration,
                    self.current_session.triggered_by,
                ),
            )
        self.current_session = None

    def shutdown(self, now: Optional[datetime] = None) -> None:
        if self.current_session is None:
            return
        end_time = self.current_session.last_active_time
        if now is not None and end_time is None:
            end_time = now
        if end_time is None:
            end_time = now or datetime.utcnow()
        self._end_session(end_time)
