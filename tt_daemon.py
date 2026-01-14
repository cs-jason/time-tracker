#!/usr/bin/env python3
"""Daemon loop for activity tracking."""
from __future__ import annotations

import argparse
import json
import logging
import os
import select
import signal
import socket
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

import fcntl

from tt_activity import frameworks_available, get_current_activity, permission_status
from tt_blocks import update_activity_block
from tt_db import (
    DB_PATH,
    TT_DIR,
    ensure_db_permissions,
    format_utc_timestamp,
    get_db_connection,
    init_database,
    load_config,
    set_setting,
)
from tt_maintenance import maybe_backup, prune_data
from tt_models import Activity
from tt_sessions import SessionManager
from tt_utils import human_duration

PID_PATH = TT_DIR / "tt.pid"
LOCK_PATH = TT_DIR / "tt.lock"
SOCK_PATH = TT_DIR / "tt.sock"
LOG_PATH = TT_DIR / "tt.log"


class SingleInstanceLock:
    """Ensure only one daemon instance runs at a time."""

    def __init__(self, lock_path: Path):
        self.lock_path = lock_path
        self.lock_file: Optional[object] = None

    def acquire(self) -> bool:
        try:
            self.lock_file = open(self.lock_path, "w")
            fcntl.flock(self.lock_file.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
            return True
        except (IOError, OSError):
            if self.lock_file:
                self.lock_file.close()
            return False

    def release(self) -> None:
        if self.lock_file:
            try:
                fcntl.flock(self.lock_file.fileno(), fcntl.LOCK_UN)
            finally:
                self.lock_file.close()
                self.lock_file = None


class TTDaemon:
    def __init__(self, foreground: bool = False):
        self.running = True
        self.foreground = foreground
        self.config = load_config(DB_PATH)
        self.session_manager = SessionManager(self.config, DB_PATH)
        self.lock = SingleInstanceLock(LOCK_PATH)
        self.ipc_socket: Optional[socket.socket] = None
        self.last_activity: Optional[Activity] = None
        self.last_prune_date: Optional[str] = None
        self.setup_logging()

    def setup_logging(self) -> None:
        log_format = "[%(asctime)s] %(message)s"
        date_format = "%Y-%m-%d %H:%M:%S"

        handlers = [logging.FileHandler(str(LOG_PATH))]
        if self.foreground:
            handlers.append(logging.StreamHandler(sys.stdout))

        logging.basicConfig(
            level=logging.INFO,
            format=log_format,
            datefmt=date_format,
            handlers=handlers,
        )

    def setup_ipc_socket(self) -> None:
        if SOCK_PATH.exists():
            SOCK_PATH.unlink()
        self.ipc_socket = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        self.ipc_socket.bind(str(SOCK_PATH))
        self.ipc_socket.listen(1)
        self.ipc_socket.setblocking(False)
        os.chmod(SOCK_PATH, 0o600)

    def run(self) -> None:
        if not self.lock.acquire():
            print("Another daemon instance is already running", file=sys.stderr)
            sys.exit(1)

        signal.signal(signal.SIGTERM, self.handle_signal)
        signal.signal(signal.SIGINT, self.handle_signal)

        ensure_db_permissions(DB_PATH)
        self.setup_ipc_socket()
        PID_PATH.write_text(str(os.getpid()))
        os.chmod(PID_PATH, 0o600)

        permissions = permission_status()
        if permissions.accessibility is False:
            logging.warning("Accessibility permission not granted - window titles unavailable")

        logging.info("Started monitoring")

        try:
            while self.running:
                try:
                    self.handle_ipc()
                    self.config = load_config(DB_PATH)
                    self.session_manager.update_config(self.config)

                    activity = get_current_activity(self.config.idle_threshold)
                    self.last_activity = activity
                    self.save_activity(activity)
                    update_activity_block(activity, DB_PATH)
                    self.session_manager.process_activity(activity)

                    self.maybe_prune()
                    maybe_backup(DB_PATH)

                    time.sleep(self.config.poll_interval)
                except Exception as exc:
                    logging.error(f"Error in main loop: {exc}")
        finally:
            self.shutdown()

    def maybe_prune(self) -> None:
        today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        if self.last_prune_date == today:
            return
        prune_data(DB_PATH)
        self.last_prune_date = today

    def save_activity(self, activity: Activity) -> None:
        with get_db_connection(DB_PATH) as conn:
            conn.execute(
                "INSERT INTO activities "
                "(timestamp, app_name, bundle_id, window_title, file_path, url, idle) "
                "VALUES (?, ?, ?, ?, ?, ?, ?)",
                (
                    format_utc_timestamp(activity.timestamp),
                    activity.app_name,
                    activity.bundle_id,
                    activity.window_title,
                    activity.file_path,
                    activity.url,
                    1 if activity.idle else 0,
                ),
            )

    def handle_signal(self, signum, _frame) -> None:
        logging.info(f"Received signal {signum}, shutting down")
        self.running = False

    def handle_ipc(self) -> None:
        if not self.ipc_socket:
            return

        try:
            readable, _, _ = select.select([self.ipc_socket], [], [], 0)
            if not readable:
                return
            conn, _ = self.ipc_socket.accept()
            try:
                data = conn.recv(4096).decode().strip()
                response = self.process_ipc_command(data)
                conn.sendall((response + "\n").encode())
            finally:
                conn.close()
        except Exception as exc:
            logging.warning(f"IPC error: {exc}")

    def process_ipc_command(self, command: str) -> str:
        if command == "PAUSE":
            set_setting("tracking_paused", "1", DB_PATH)
            set_setting("tracking_paused_at", format_utc_timestamp(datetime.now(timezone.utc)), DB_PATH)
            self.session_manager.pause(datetime.now(timezone.utc))
            return "OK"
        if command == "RESUME":
            set_setting("tracking_paused", "0", DB_PATH)
            set_setting("tracking_paused_at", None, DB_PATH)
            return "OK"
        if command == "STATUS":
            return json.dumps(self.status_payload())
        if command == "PING":
            return "OK"
        return "ERROR:Unknown command"

    def status_payload(self) -> dict:
        now = datetime.now(timezone.utc)
        current = self.session_manager.current_session
        duration = self.session_manager.current_duration(now)
        permissions = permission_status()
        payload = {
            "tracking_paused": bool(self.config.tracking_paused),
            "last_activity": self._serialize_activity(self.last_activity),
            "permissions": {
                "accessibility": permissions.accessibility,
                "automation": permissions.automation,
                "screen_recording": permissions.screen_recording,
            },
        }

        if current:
            grace_remaining = None
            if self.last_activity and self.last_activity.idle:
                elapsed = (now - current.last_active_time).total_seconds()
                grace_remaining = max(0, self.config.idle_grace_period - int(elapsed))
            payload["session"] = {
                "project_id": current.project_id,
                "triggered_by": current.triggered_by,
                "duration": duration,
                "grace_remaining": grace_remaining,
            }
        else:
            payload["session"] = None
        return payload

    def _serialize_activity(self, activity: Optional[Activity]) -> Optional[dict]:
        if activity is None:
            return None
        return {
            "timestamp": format_utc_timestamp(activity.timestamp),
            "app_name": activity.app_name,
            "bundle_id": activity.bundle_id,
            "window_title": activity.window_title,
            "file_path": activity.file_path,
            "url": activity.url,
            "idle": activity.idle,
        }

    def shutdown(self) -> None:
        self.session_manager.shutdown(datetime.now(timezone.utc))
        if self.ipc_socket:
            self.ipc_socket.close()
            if SOCK_PATH.exists():
                SOCK_PATH.unlink()
        if PID_PATH.exists():
            PID_PATH.unlink()
        self.lock.release()
        logging.info("Daemon stopped")


def main(foreground: bool = False) -> None:
    TT_DIR.mkdir(mode=0o700, exist_ok=True)
    init_database(DB_PATH)
    ensure_db_permissions(DB_PATH)
    ok, reason = frameworks_available()
    if not ok:
        message = (
            "macOS frameworks not available. "
            "Install PyObjC (pip3 install pyobjc) and retry."
        )
        if reason:
            message = f"{message} ({reason})"
        print(message, file=sys.stderr)
        sys.exit(1)
    daemon = TTDaemon(foreground=foreground)
    daemon.run()


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--foreground", action="store_true")
    args = parser.parse_args()
    main(foreground=args.foreground)
