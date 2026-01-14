#!/usr/bin/env python3
"""Database maintenance utilities (pruning, backups)."""
from __future__ import annotations

import os
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Optional

from tt_db import DB_PATH, TT_DIR, format_utc_timestamp, get_db_connection, load_config

BACKUP_DIR = TT_DIR / "backups"


def prune_data(db_path: Path = DB_PATH, now: Optional[datetime] = None) -> dict:
    now = now or datetime.now(timezone.utc)
    config = load_config(db_path)
    stats = {"activities": 0, "activity_blocks": 0, "sessions": 0}

    with get_db_connection(db_path) as conn:
        if config.retention_days > 0:
            cutoff = now - timedelta(days=config.retention_days)
            cutoff_str = format_utc_timestamp(cutoff)
            cur = conn.execute(
                "DELETE FROM activities WHERE timestamp < ?",
                (cutoff_str,),
            )
            stats["activities"] = cur.rowcount

        if config.blocks_retention_days > 0:
            cutoff = now - timedelta(days=config.blocks_retention_days)
            cutoff_str = format_utc_timestamp(cutoff)
            cur = conn.execute(
                "DELETE FROM activity_blocks WHERE start_time < ?",
                (cutoff_str,),
            )
            stats["activity_blocks"] = cur.rowcount

        if config.sessions_retention_days and config.sessions_retention_days > 0:
            cutoff = now - timedelta(days=config.sessions_retention_days)
            cutoff_str = format_utc_timestamp(cutoff)
            cur = conn.execute(
                "DELETE FROM sessions WHERE start_time < ?",
                (cutoff_str,),
            )
            stats["sessions"] = cur.rowcount

    return stats


def backup_database(
    db_path: Path = DB_PATH,
    backup_dir: Path = BACKUP_DIR,
    now: Optional[datetime] = None,
) -> Path:
    now = now or datetime.now(timezone.utc)
    backup_dir.mkdir(mode=0o700, exist_ok=True)
    filename = f"tt-{now.strftime('%Y%m%d')}.db"
    target = backup_dir / filename

    with get_db_connection(db_path) as src:
        with get_db_connection(target) as dest:
            src.backup(dest)

    try:
        os.chmod(target, 0o600)
    except OSError:
        pass
    return target


def maybe_backup(db_path: Path = DB_PATH, backup_dir: Path = BACKUP_DIR) -> Optional[Path]:
    backup_dir.mkdir(mode=0o700, exist_ok=True)
    backups = sorted(backup_dir.glob("tt-*.db"), key=lambda p: p.stat().st_mtime)
    now = datetime.now(timezone.utc)
    if backups:
        latest = backups[-1]
        age = now - datetime.fromtimestamp(latest.stat().st_mtime, tz=timezone.utc)
        if age < timedelta(days=7):
            return None
    return backup_database(db_path=db_path, backup_dir=backup_dir, now=now)
