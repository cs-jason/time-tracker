#!/usr/bin/env python3
"""Shared DB utilities (no macOS dependencies)."""
from __future__ import annotations

import os
import sqlite3
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional, Dict

TT_DIR = Path.home() / ".tt"
DB_PATH = TT_DIR / "tt.db"

DEFAULT_SETTINGS: Dict[str, Optional[str]] = {
    "poll_interval": "2",
    "idle_threshold": "120",
    "idle_grace_period": "300",
    "session_grace_period": "120",
    "min_session_duration": "60",
    "retention_days": "90",
    "blocks_retention_days": "90",
    "sessions_retention_days": "0",
    "week_start": "monday",
    "tracking_paused": "0",
    "tracking_paused_at": None,
}


@dataclass
class Config:
    """Runtime configuration loaded from settings table."""
    poll_interval: int = 2
    idle_threshold: int = 120
    idle_grace_period: int = 300
    session_grace_period: int = 120
    min_session_duration: int = 60
    retention_days: int = 90
    blocks_retention_days: int = 90
    sessions_retention_days: int = 0
    week_start: str = "monday"
    tracking_paused: int = 0
    tracking_paused_at: Optional[str] = None


SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS activities (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    timestamp TEXT NOT NULL,
    app_name TEXT,
    bundle_id TEXT,
    window_title TEXT,
    file_path TEXT,
    url TEXT,
    idle INTEGER DEFAULT 0,
    created_at TEXT DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS activity_blocks (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    start_time TEXT NOT NULL,
    end_time TEXT NOT NULL,
    duration INTEGER NOT NULL,
    app_name TEXT,
    bundle_id TEXT,
    window_title TEXT,
    file_path TEXT,
    url TEXT,
    idle INTEGER DEFAULT 0
);

CREATE TABLE IF NOT EXISTS projects (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT UNIQUE NOT NULL,
    color TEXT DEFAULT '#808080',
    archived INTEGER DEFAULT 0,
    created_at TEXT DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS rules (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    project_id INTEGER NOT NULL,
    rule_type TEXT NOT NULL,
    rule_value TEXT NOT NULL,
    rule_group INTEGER DEFAULT 0,
    enabled INTEGER DEFAULT 1,
    created_at TEXT DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (project_id) REFERENCES projects(id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS sessions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    project_id INTEGER NOT NULL,
    start_time TEXT NOT NULL,
    end_time TEXT NOT NULL,
    duration INTEGER NOT NULL,
    triggered_by TEXT,
    created_at TEXT DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (project_id) REFERENCES projects(id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS settings (
    key TEXT PRIMARY KEY,
    value TEXT
);

CREATE INDEX IF NOT EXISTS idx_activities_timestamp ON activities(timestamp);
CREATE INDEX IF NOT EXISTS idx_activities_bundle_id ON activities(bundle_id);
CREATE INDEX IF NOT EXISTS idx_blocks_start ON activity_blocks(start_time);
CREATE INDEX IF NOT EXISTS idx_sessions_start ON sessions(start_time);
CREATE INDEX IF NOT EXISTS idx_sessions_project ON sessions(project_id);
CREATE INDEX IF NOT EXISTS idx_rules_project ON rules(project_id);
"""


def ensure_tt_dir() -> None:
    """Ensure ~/.tt/ directory exists with correct permissions."""
    TT_DIR.mkdir(mode=0o700, exist_ok=True)


def _set_restrictive_umask() -> int:
    """Set umask to 077 and return previous value."""
    return os.umask(0o077)


def _restore_umask(previous: int) -> None:
    os.umask(previous)


def ensure_db_permissions(db_path: Path = DB_PATH) -> None:
    """Ensure DB and WAL/SHM files have 600 permissions."""
    for path in [db_path, db_path.with_suffix(".db-wal"), db_path.with_suffix(".db-shm")]:
        if path.exists():
            try:
                os.chmod(path, 0o600)
            except OSError:
                pass


def get_db_connection(db_path: Path = DB_PATH) -> sqlite3.Connection:
    """Open a SQLite connection with required pragmas."""
    ensure_tt_dir()
    old_umask = _set_restrictive_umask()
    new_db = not db_path.exists()
    try:
        conn = sqlite3.connect(str(db_path), timeout=5)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON")
        conn.execute("PRAGMA journal_mode = WAL")
        conn.execute("PRAGMA busy_timeout = 5000")
    finally:
        _restore_umask(old_umask)

    if new_db:
        try:
            os.chmod(db_path, 0o600)
        except OSError:
            pass
    return conn


def init_database(db_path: Path = DB_PATH) -> None:
    """Initialize database schema and default settings."""
    with get_db_connection(db_path) as conn:
        conn.executescript(SCHEMA_SQL)
        for key, value in DEFAULT_SETTINGS.items():
            conn.execute(
                "INSERT OR IGNORE INTO settings (key, value) VALUES (?, ?)",
                (key, value),
            )

    ensure_db_permissions(db_path)


def load_config(db_path: Path = DB_PATH) -> Config:
    """Load configuration from settings table."""
    config = Config()
    try:
        with get_db_connection(db_path) as conn:
            rows = conn.execute("SELECT key, value FROM settings").fetchall()
            settings = {row["key"]: row["value"] for row in rows}
    except sqlite3.OperationalError:
        return config

    if "poll_interval" in settings:
        config.poll_interval = int(settings["poll_interval"])
    if "idle_threshold" in settings:
        config.idle_threshold = int(settings["idle_threshold"])
    if "idle_grace_period" in settings:
        config.idle_grace_period = int(settings["idle_grace_period"])
    if "session_grace_period" in settings:
        config.session_grace_period = int(settings["session_grace_period"])
    if "min_session_duration" in settings:
        config.min_session_duration = int(settings["min_session_duration"])
    if "retention_days" in settings:
        config.retention_days = int(settings["retention_days"])
    if "blocks_retention_days" in settings:
        config.blocks_retention_days = int(settings["blocks_retention_days"])
    if "sessions_retention_days" in settings:
        config.sessions_retention_days = int(settings["sessions_retention_days"])
    if "week_start" in settings:
        config.week_start = settings["week_start"]
    if "tracking_paused" in settings:
        config.tracking_paused = int(settings["tracking_paused"])
    if "tracking_paused_at" in settings:
        config.tracking_paused_at = settings["tracking_paused_at"]

    return config


def get_setting(key: str, db_path: Path = DB_PATH) -> Optional[str]:
    with get_db_connection(db_path) as conn:
        row = conn.execute("SELECT value FROM settings WHERE key = ?", (key,)).fetchone()
    return row["value"] if row else None


def set_setting(key: str, value: Optional[str], db_path: Path = DB_PATH) -> None:
    with get_db_connection(db_path) as conn:
        conn.execute(
            "INSERT INTO settings (key, value) VALUES (?, ?) "
            "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
            (key, value),
        )


def format_utc_timestamp(dt: datetime) -> str:
    """Format datetime as UTC ISO 8601 with Z suffix."""
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def parse_utc_timestamp(value: str) -> datetime:
    """Parse UTC ISO 8601 with Z suffix into aware datetime."""
    return datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone(timezone.utc)


def utc_now() -> datetime:
    return datetime.now(timezone.utc)
