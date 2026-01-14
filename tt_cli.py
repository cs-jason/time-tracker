#!/usr/bin/env python3
"""CLI entrypoint for tt."""
from __future__ import annotations

import argparse
import csv
import json
import os
import shutil
import signal
import socket
import subprocess
import sys
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Iterable, List, Optional, Tuple

from tt_activity import frameworks_available, get_current_activity
from tt_db import (
    DB_PATH,
    TT_DIR,
    DEFAULT_SETTINGS,
    ensure_db_permissions,
    format_utc_timestamp,
    get_db_connection,
    init_database,
    load_config,
    set_setting,
    get_setting,
    parse_utc_timestamp,
)
from tt_maintenance import backup_database, prune_data
from tt_output import print_table
from tt_rules import RULE_TYPES, RuleEngine
from tt_utils import (
    format_local_timestamp,
    human_duration,
    human_duration_short,
    local_day_bounds,
    parse_local_date,
    utc_range_to_strings,
)

SOCK_PATH = TT_DIR / "tt.sock"
PID_PATH = TT_DIR / "tt.pid"


class CliError(Exception):
    pass


def projects_list(include_archived: bool) -> None:
    where = "" if include_archived else "WHERE archived = 0"
    with get_db_connection(DB_PATH) as conn:
        rows = conn.execute(
            f"SELECT id, name, color, archived FROM projects {where} ORDER BY id"
        ).fetchall()
    if not rows:
        print("No projects found.")
        return
    print_table(
        ["ID", "Name", "Color", "Archived"],
        [
            [
                str(row["id"]),
                row["name"],
                row["color"],
                "yes" if row["archived"] else "no",
            ]
            for row in rows
        ],
    )


def projects_add(name: str, color: Optional[str]) -> None:
    with get_db_connection(DB_PATH) as conn:
        try:
            conn.execute(
                "INSERT INTO projects (name, color) VALUES (?, ?)",
                (name, color or "#808080"),
            )
        except Exception as exc:
            raise CliError(f"Failed to create project: {exc}") from exc
    print(f"✓ Created project: {name}")


def projects_archive(project_id: int, archived: int) -> None:
    with get_db_connection(DB_PATH) as conn:
        cur = conn.execute(
            "UPDATE projects SET archived = ? WHERE id = ?",
            (archived, project_id),
        )
    if cur.rowcount == 0:
        raise CliError(f"Project {project_id} not found")
    state = "Archived" if archived else "Unarchived"
    print(f"✓ {state} project {project_id}")


def projects_remove(project_id: int) -> None:
    with get_db_connection(DB_PATH) as conn:
        cur = conn.execute("DELETE FROM projects WHERE id = ?", (project_id,))
    if cur.rowcount == 0:
        raise CliError(f"Project {project_id} not found")
    print(f"✓ Removed project {project_id}")


def rules_list(project_id: Optional[int]) -> None:
    where = ""
    params: List[object] = []
    if project_id is not None:
        where = "WHERE project_id = ?"
        params.append(project_id)
    with get_db_connection(DB_PATH) as conn:
        rows = conn.execute(
            f"SELECT id, project_id, rule_type, rule_value, rule_group, enabled "
            f"FROM rules {where} ORDER BY project_id, rule_group, id",
            params,
        ).fetchall()
    if not rows:
        print("No rules found.")
        return
    print_table(
        ["ID", "Project", "Type", "Value", "Group", "Enabled"],
        [
            [
                str(row["id"]),
                str(row["project_id"]),
                row["rule_type"],
                row["rule_value"],
                str(row["rule_group"]),
                "yes" if row["enabled"] else "no",
            ]
            for row in rows
        ],
    )


def rules_add(
    project_id: int,
    rule_type: str,
    rule_value: str,
    rule_group: int,
    enabled: bool,
) -> None:
    if rule_type not in RULE_TYPES:
        raise CliError(f"Invalid rule type: {rule_type}")

    with get_db_connection(DB_PATH) as conn:
        project = conn.execute(
            "SELECT id FROM projects WHERE id = ?", (project_id,)
        ).fetchone()
        if not project:
            raise CliError(f"Project {project_id} not found")
        conn.execute(
            "INSERT INTO rules (project_id, rule_type, rule_value, rule_group, enabled) "
            "VALUES (?, ?, ?, ?, ?)",
            (project_id, rule_type, rule_value, rule_group, 1 if enabled else 0),
        )
    print(f"✓ Added rule to project {project_id}")


def rules_remove(rule_id: int) -> None:
    with get_db_connection(DB_PATH) as conn:
        cur = conn.execute("DELETE FROM rules WHERE id = ?", (rule_id,))
    if cur.rowcount == 0:
        raise CliError(f"Rule {rule_id} not found")
    print(f"✓ Removed rule {rule_id}")


def rules_toggle(rule_id: int, enabled: bool) -> None:
    with get_db_connection(DB_PATH) as conn:
        cur = conn.execute(
            "UPDATE rules SET enabled = ? WHERE id = ?",
            (1 if enabled else 0, rule_id),
        )
    if cur.rowcount == 0:
        raise CliError(f"Rule {rule_id} not found")
    state = "Enabled" if enabled else "Disabled"
    print(f"✓ {state} rule {rule_id}")


def rules_test() -> None:
    activity = None
    try:
        activity = get_current_activity(load_config(DB_PATH).idle_threshold)
    except Exception:
        with get_db_connection(DB_PATH) as conn:
            row = conn.execute(
                "SELECT timestamp, app_name, bundle_id, window_title, file_path, url, idle "
                "FROM activities ORDER BY timestamp DESC LIMIT 1"
            ).fetchone()
        if row:
            activity = type("Temp", (), {})()
            activity.timestamp = parse_utc_timestamp(row["timestamp"])
            activity.app_name = row["app_name"]
            activity.bundle_id = row["bundle_id"]
            activity.window_title = row["window_title"]
            activity.file_path = row["file_path"]
            activity.url = row["url"]
            activity.idle = bool(row["idle"])

    if not activity:
        print("No activity available to test.")
        return

    engine = RuleEngine(DB_PATH)
    match = engine.match(activity)
    if not match:
        print("No rules match current activity.")
        return

    with get_db_connection(DB_PATH) as conn:
        proj = conn.execute(
            "SELECT name FROM projects WHERE id = ?", (match.project_id,)
        ).fetchone()
    name = proj["name"] if proj else f"Project {match.project_id}"
    print("Current activity matches:")
    print(f"  → {name} ({match.triggered_by})")


def config_list() -> None:
    with get_db_connection(DB_PATH) as conn:
        rows = conn.execute("SELECT key, value FROM settings ORDER BY key").fetchall()
    settings = {row["key"]: row["value"] for row in rows}
    settings["db_path"] = str(DB_PATH)
    print_table(
        ["Key", "Value"],
        [[key, "" if value is None else str(value)] for key, value in settings.items()],
    )


def config_get(key: str) -> None:
    if key == "db_path":
        print(DB_PATH)
        return
    value = get_setting(key)
    if value is None:
        raise CliError(f"Unknown setting: {key}")
    print(value)


def config_set(key: str, value: str) -> None:
    if key == "db_path":
        raise CliError("db_path is read-only")
    if key not in DEFAULT_SETTINGS:
        raise CliError(f"Unknown setting: {key}")
    normalized: Optional[str] = value
    if value.lower() in {"none", "null"}:
        normalized = None
    set_setting(key, normalized)
    print(f"✓ Set {key}")


def _daemon_request(command: str) -> Optional[str]:
    if not SOCK_PATH.exists():
        return None
    try:
        with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as client:
            client.settimeout(1)
            client.connect(str(SOCK_PATH))
            client.sendall((command + "\n").encode())
            data = client.recv(4096).decode().strip()
            return data
    except (FileNotFoundError, ConnectionRefusedError, socket.timeout, OSError):
        return None


def _daemon_running() -> bool:
    response = _daemon_request("PING")
    return response == "OK"


def status_show() -> None:
    payload = None
    response = _daemon_request("STATUS")
    if response:
        try:
            payload = json.loads(response)
        except json.JSONDecodeError:
            payload = None

    now = datetime.now(timezone.utc)
    print("Current Activity")
    print("────────────────────────────────────────────────────")

    if payload and payload.get("last_activity"):
        last = payload["last_activity"]
        ts = parse_utc_timestamp(last["timestamp"])
        since = human_duration_short((now - ts).total_seconds())
        if last.get("idle"):
            print(f"Status:   Idle ({since})")
            label = last.get("app_name") or "Unknown"
            window = last.get("window_title") or ""
            if window:
                print(f"Last:     {label} - {window}")
            else:
                print(f"Last:     {label}")
        else:
            print(f"App:      {last.get('app_name') or 'Unknown'}")
            if last.get("window_title"):
                print(f"Window:   {last['window_title']}")
            if last.get("file_path"):
                print(f"Path:     {last['file_path']}")
            if last.get("url"):
                print(f"URL:      {last['url']}")
            print(f"Since:    {since} ago")
    else:
        last = _last_activity_row()
        if not last:
            print("No activity recorded yet.")
        else:
            ts = parse_utc_timestamp(last["timestamp"])
            since = human_duration_short((now - ts).total_seconds())
            if last["idle"]:
                print(f"Status:   Idle ({since})")
            else:
                print(f"App:      {last['app_name'] or 'Unknown'}")
                if last["window_title"]:
                    print(f"Window:   {last['window_title']}")
                if last["file_path"]:
                    print(f"Path:     {last['file_path']}")
                if last["url"]:
                    print(f"URL:      {last['url']}")
                print(f"Since:    {since} ago")

    print("\nAuto-Tracking")
    print("────────────────────────────────────────────────────")

    config = load_config(DB_PATH)
    tracking_paused = bool(payload.get("tracking_paused")) if payload else bool(config.tracking_paused)
    if tracking_paused:
        print("Tracking paused")
        if config.tracking_paused_at:
            print(f"Paused at: {config.tracking_paused_at}")
        print()

    if payload and payload.get("session"):
        session = payload["session"]
        project_name = _project_name(session["project_id"])
        duration = human_duration(session["duration"] or 0)
        print(f"Project:  {project_name}")
        print(f"Rule:     {session['triggered_by']}")
        print(f"Duration: {duration} (this session)")
        grace = session.get("grace_remaining")
        if grace is not None:
            print(f"Grace:    {human_duration_short(grace)} remaining")
    else:
        # Try to infer based on last activity + rules
        last = _last_activity_row()
        if last and not last["idle"]:
            engine = RuleEngine(DB_PATH)
            temp = type("Temp", (), {})()
            temp.timestamp = parse_utc_timestamp(last["timestamp"])
            temp.app_name = last["app_name"]
            temp.bundle_id = last["bundle_id"]
            temp.window_title = last["window_title"]
            temp.file_path = last["file_path"]
            temp.url = last["url"]
            temp.idle = bool(last["idle"])
            match = engine.match(temp)
            if match:
                project_name = _project_name(match.project_id)
                print(f"Project:  {project_name}")
                print(f"Rule:     {match.triggered_by}")
                return
        print("Not tracking (no rules match)")


def today_show() -> None:
    today = date.today()
    start_utc, end_utc = local_day_bounds(today)
    title = today.strftime("%A, %B %-d, %Y")
    _stats_for_range(start_utc, end_utc, title_prefix=f"Today: {title}")


def stats_show(period: Optional[str], from_date: Optional[str], to_date: Optional[str]) -> None:
    config = load_config(DB_PATH)
    today = date.today()

    if (from_date and not to_date) or (to_date and not from_date):
        raise CliError("Both --from and --to are required")
    if from_date and to_date:
        start_utc, end_utc = local_day_bounds(parse_local_date(from_date))
        end_utc = local_day_bounds(parse_local_date(to_date))[1]
        title = f"{from_date} - {to_date}"
    else:
        period = period or "week"
        if period == "day":
            start_utc, end_utc = local_day_bounds(today)
            title = today.strftime("%B %-d, %Y")
        elif period == "week":
            start_date, end_date = _week_range(today, config.week_start)
            start_utc, end_utc = local_day_bounds(start_date)[0], local_day_bounds(end_date)[1]
            title = f"{start_date.strftime('%B %-d')} - {end_date.strftime('%B %-d, %Y')}"
        elif period == "month":
            start_date = today.replace(day=1)
            next_month = (start_date.replace(day=28) + timedelta(days=4)).replace(day=1)
            end_date = next_month - timedelta(days=1)
            start_utc, end_utc = local_day_bounds(start_date)[0], local_day_bounds(end_date)[1]
            title = start_date.strftime("%B %Y")
        elif period == "year":
            start_date = date(today.year, 1, 1)
            end_date = date(today.year, 12, 31)
            start_utc, end_utc = local_day_bounds(start_date)[0], local_day_bounds(end_date)[1]
            title = str(today.year)
        else:
            raise CliError("Invalid period. Use day|week|month|year")

    _stats_for_range(start_utc, end_utc, title_prefix=title)


def _week_range(today: date, week_start: str) -> Tuple[date, date]:
    start_map = {"monday": 0, "sunday": 6}
    start_day = start_map.get(week_start.lower(), 0)
    delta = (today.weekday() - start_day) % 7
    start = today - timedelta(days=delta)
    end = start + timedelta(days=6)
    return start, end


def _stats_for_range(start_utc: datetime, end_utc: datetime, title_prefix: str) -> None:
    sessions = _fetch_sessions(start_utc, end_utc)
    projects = _aggregate_sessions(sessions, start_utc, end_utc)
    totals = sum(p["duration"] for p in projects.values())
    total_sessions = sum(p["count"] for p in projects.values())

    config = load_config(DB_PATH)
    active_seconds, idle_seconds = _activity_totals(start_utc, end_utc, config.poll_interval)
    untracked = max(0, active_seconds - totals)

    print(f"{title_prefix}")
    print("────────────────────────────────────────────────────")

    if not projects:
        print("No tracked sessions in this period.")
    else:
        print_table(
            ["Project", "Time", "Sessions"],
            [
                [
                    data["name"],
                    human_duration(data["duration"]),
                    str(data["count"]),
                ]
                for data in projects.values()
            ],
        )

    print("────────────────────────────────────────────────────")
    print(f"Total Tracked              {human_duration(totals)}    {total_sessions}")
    print(f"Total Active               {human_duration(active_seconds)}")
    print(f"Untracked                  {human_duration(untracked)}")
    print(f"Idle                       {human_duration(idle_seconds)}")


def activity_show(limit: int, date_str: Optional[str], from_date: Optional[str], to_date: Optional[str]) -> None:
    query = "SELECT timestamp, app_name, window_title, file_path, url, idle FROM activities"
    params: List[str] = []

    if (from_date and not to_date) or (to_date and not from_date):
        raise CliError("Both --from and --to are required")
    if date_str:
        start_utc, end_utc = local_day_bounds(parse_local_date(date_str))
        start_str, end_str = utc_range_to_strings(start_utc, end_utc)
        query += " WHERE timestamp >= ? AND timestamp <= ?"
        params.extend([start_str, end_str])
    elif from_date and to_date:
        start_utc, end_utc = local_day_bounds(parse_local_date(from_date))
        end_utc = local_day_bounds(parse_local_date(to_date))[1]
        start_str, end_str = utc_range_to_strings(start_utc, end_utc)
        query += " WHERE timestamp >= ? AND timestamp <= ?"
        params.extend([start_str, end_str])

    query += " ORDER BY timestamp DESC LIMIT ?"
    params.append(str(limit))

    with get_db_connection(DB_PATH) as conn:
        rows = conn.execute(query, params).fetchall()

    if not rows:
        print("No activity samples found.")
        return

    print_table(
        ["Time", "App", "Window", "Path/URL", "Idle"],
        [
            [
                format_local_timestamp(row["timestamp"]),
                row["app_name"] or "",
                row["window_title"] or "",
                row["file_path"] or (row["url"] or ""),
                "yes" if row["idle"] else "no",
            ]
            for row in rows
        ],
    )


def export_data(
    output: str,
    fmt: str,
    from_date: Optional[str],
    to_date: Optional[str],
    table: str,
) -> None:
    if not output:
        raise CliError("--output is required")

    if (from_date and not to_date) or (to_date and not from_date):
        raise CliError("Both --from and --to are required")
    if from_date and to_date:
        start_utc, end_utc = local_day_bounds(parse_local_date(from_date))
        end_utc = local_day_bounds(parse_local_date(to_date))[1]
    else:
        start_utc, end_utc = None, None

    if table == "sessions":
        rows = _fetch_sessions(start_utc, end_utc)
        records = []
        for row in rows:
            project_name = _project_name(row["project_id"])
            records.append(
                {
                    "project_id": row["project_id"],
                    "project_name": project_name,
                    "start_time": row["start_time"],
                    "end_time": row["end_time"],
                    "duration": row["duration"],
                    "triggered_by": row["triggered_by"],
                }
            )
    elif table == "activities":
        records = _fetch_activities(start_utc, end_utc)
    else:
        raise CliError("Invalid table. Use sessions|activities")

    if fmt == "json":
        with open(output, "w", encoding="utf-8") as f:
            json.dump(records, f, indent=2)
    elif fmt == "csv":
        if not records:
            raise CliError("No records found for export")
        with open(output, "w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=list(records[0].keys()))
            writer.writeheader()
            writer.writerows(records)
    else:
        raise CliError("Invalid format. Use csv|json")

    print(f"✓ Exported {len(records)} records to {output}")


def tracking_pause() -> None:
    set_setting("tracking_paused", "1", DB_PATH)
    set_setting("tracking_paused_at", format_utc_timestamp(datetime.now(timezone.utc)), DB_PATH)
    _daemon_request("PAUSE")
    print("✓ Tracking paused")


def tracking_resume() -> None:
    set_setting("tracking_paused", "0", DB_PATH)
    set_setting("tracking_paused_at", None, DB_PATH)
    _daemon_request("RESUME")
    print("✓ Tracking resumed")


def tracking_status() -> None:
    config = load_config(DB_PATH)
    if config.tracking_paused:
        print("Tracking is paused")
        if config.tracking_paused_at:
            print(f"Paused at: {config.tracking_paused_at}")
    else:
        print("Tracking is active")


def daemon_start(foreground: bool) -> None:
    if _daemon_running():
        print("Daemon already running")
        return
    ok, reason = frameworks_available()
    if not ok:
        message = (
            "macOS frameworks not available. "
            "Install PyObjC (pip3 install pyobjc) and retry."
        )
        if reason:
            message = f"{message} ({reason})"
        raise CliError(message)

    if foreground:
        from tt_daemon import main as daemon_main

        daemon_main(foreground=True)
        return

    daemon_path = Path(__file__).with_name("tt_daemon.py")
    subprocess.Popen(
        [sys.executable, str(daemon_path), "--foreground"],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        start_new_session=True,
    )
    print("✓ Daemon started")


def daemon_stop() -> None:
    if not PID_PATH.exists():
        print("Daemon not running")
        return
    pid = int(PID_PATH.read_text().strip())
    try:
        os.kill(pid, signal.SIGTERM)
    except ProcessLookupError:
        print("Daemon not running")
        return
    print("✓ Daemon stopped")


def daemon_status() -> None:
    if _daemon_running():
        print("Daemon Status: Running")
        response = _daemon_request("STATUS")
        if response:
            try:
                payload = json.loads(response)
                perms = payload.get("permissions", {})
                print("Permissions:")
                print(f"  Accessibility: {format_perm(perms.get('accessibility'))}")
                print(f"  Automation:    {format_perm(perms.get('automation'))}")
                print(f"  Screen Recording: {format_perm(perms.get('screen_recording'))}")
            except json.JSONDecodeError:
                pass
    else:
        print("Daemon Status: Not running")


def daemon_install() -> None:
    agent_dir = Path.home() / "Library" / "LaunchAgents"
    agent_dir.mkdir(parents=True, exist_ok=True)
    plist_path = agent_dir / "com.tt.daemon.plist"

    tt_path = shutil.which("tt") or str(Path(sys.argv[0]).resolve())
    home = str(Path.home())

    plist = f"""<?xml version=\"1.0\" encoding=\"UTF-8\"?>
<!DOCTYPE plist PUBLIC \"-//Apple//DTD PLIST 1.0//EN\" \"http://www.apple.com/DTDs/PropertyList-1.0.dtd\">
<plist version=\"1.0\">
<dict>
    <key>Label</key>
    <string>com.tt.daemon</string>
    <key>ProgramArguments</key>
    <array>
        <string>{tt_path}</string>
        <string>daemon</string>
        <string>start</string>
        <string>--foreground</string>
    </array>
    <key>RunAtLoad</key>
    <true/>
    <key>KeepAlive</key>
    <true/>
    <key>StandardOutPath</key>
    <string>{home}/.tt/tt.log</string>
    <key>StandardErrorPath</key>
    <string>{home}/.tt/tt.log</string>
    <key>WorkingDirectory</key>
    <string>{home}</string>
    <key>EnvironmentVariables</key>
    <dict>
        <key>PATH</key>
        <string>/usr/local/bin:/usr/bin:/bin:{home}/.local/bin</string>
        <key>HOME</key>
        <string>{home}</string>
    </dict>
</dict>
</plist>
"""
    plist_path.write_text(plist)
    print(f"✓ Installed LaunchAgent: {plist_path}")


def db_prune() -> None:
    stats = prune_data(DB_PATH)
    print("Prune complete:")
    for key, value in stats.items():
        print(f"  {key}: {value}")


def db_backup() -> None:
    path = backup_database(DB_PATH)
    print(f"✓ Backup created: {path}")


def format_perm(value: Optional[bool]) -> str:
    if value is None:
        return "? Unknown"
    return "✓ Granted" if value else "✗ Not granted"


def _fetch_sessions(start_utc: Optional[datetime], end_utc: Optional[datetime]):
    with get_db_connection(DB_PATH) as conn:
        if start_utc and end_utc:
            start_str, end_str = utc_range_to_strings(start_utc, end_utc)
            rows = conn.execute(
                "SELECT * FROM sessions WHERE end_time >= ? AND start_time <= ? ORDER BY start_time",
                (start_str, end_str),
            ).fetchall()
        else:
            rows = conn.execute("SELECT * FROM sessions ORDER BY start_time").fetchall()
    return rows


def _fetch_activities(start_utc: Optional[datetime], end_utc: Optional[datetime]):
    with get_db_connection(DB_PATH) as conn:
        if start_utc and end_utc:
            start_str, end_str = utc_range_to_strings(start_utc, end_utc)
            rows = conn.execute(
                "SELECT * FROM activities WHERE timestamp >= ? AND timestamp <= ? ORDER BY timestamp",
                (start_str, end_str),
            ).fetchall()
        else:
            rows = conn.execute("SELECT * FROM activities ORDER BY timestamp").fetchall()

    return [dict(row) for row in rows]


def _aggregate_sessions(rows, start_utc: datetime, end_utc: datetime) -> dict:
    projects: dict = {}
    for row in rows:
        start = parse_utc_timestamp(row["start_time"])
        end = parse_utc_timestamp(row["end_time"])
        overlap = _overlap_seconds(start, end, start_utc, end_utc)
        if overlap <= 0:
            continue
        project_id = row["project_id"]
        entry = projects.setdefault(
            project_id,
            {"name": _project_name(project_id), "duration": 0, "count": 0},
        )
        entry["duration"] += overlap
        entry["count"] += 1
    return projects


def _overlap_seconds(start: datetime, end: datetime, window_start: datetime, window_end: datetime) -> int:
    latest_start = max(start, window_start)
    earliest_end = min(end, window_end)
    if earliest_end <= latest_start:
        return 0
    return int(round((earliest_end - latest_start).total_seconds()))


def _activity_totals(start_utc: datetime, end_utc: datetime, poll_interval: int) -> Tuple[int, int]:
    start_str, end_str = utc_range_to_strings(start_utc, end_utc)
    with get_db_connection(DB_PATH) as conn:
        rows = conn.execute(
            "SELECT idle, COUNT(*) as count FROM activities "
            "WHERE timestamp >= ? AND timestamp <= ? GROUP BY idle",
            (start_str, end_str),
        ).fetchall()

    idle_count = 0
    active_count = 0
    for row in rows:
        if row["idle"]:
            idle_count = row["count"]
        else:
            active_count = row["count"]

    return active_count * poll_interval, idle_count * poll_interval


def _project_name(project_id: int) -> str:
    with get_db_connection(DB_PATH) as conn:
        row = conn.execute("SELECT name FROM projects WHERE id = ?", (project_id,)).fetchone()
    return row["name"] if row else f"Project {project_id}"


def _last_activity_row():
    with get_db_connection(DB_PATH) as conn:
        row = conn.execute(
            "SELECT timestamp, app_name, bundle_id, window_title, file_path, url, idle "
            "FROM activities ORDER BY timestamp DESC LIMIT 1"
        ).fetchone()
    return row


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="tt", description="CLI time tracker")
    subparsers = parser.add_subparsers(dest="command")

    # projects
    projects_parser = subparsers.add_parser("projects", help="Manage projects")
    projects_sub = projects_parser.add_subparsers(dest="subcommand")

    projects_list_parser = projects_sub.add_parser("list", help="List projects")
    projects_list_parser.add_argument("--all", action="store_true", help="Include archived")

    projects_add_parser = projects_sub.add_parser("add", help="Add a project")
    projects_add_parser.add_argument("name")
    projects_add_parser.add_argument("--color", default=None)

    projects_archive_parser = projects_sub.add_parser("archive", help="Archive a project")
    projects_archive_parser.add_argument("project_id", type=int)

    projects_unarchive_parser = projects_sub.add_parser("unarchive", help="Unarchive a project")
    projects_unarchive_parser.add_argument("project_id", type=int)

    projects_remove_parser = projects_sub.add_parser("remove", help="Remove a project")
    projects_remove_parser.add_argument("project_id", type=int)

    # rules
    rules_parser = subparsers.add_parser("rules", help="Manage rules")
    rules_sub = rules_parser.add_subparsers(dest="subcommand")

    rules_list_parser = rules_sub.add_parser("list", help="List rules")
    rules_list_parser.add_argument("--project", type=int, default=None)

    rules_add_parser = rules_sub.add_parser("add", help="Add a rule")
    rules_add_parser.add_argument("project_id", type=int)
    rules_add_parser.add_argument("rule_type", choices=sorted(RULE_TYPES))
    rules_add_parser.add_argument("rule_value")
    rules_add_parser.add_argument("--group", type=int, default=0)
    rules_add_parser.add_argument("--disabled", action="store_true")

    rules_remove_parser = rules_sub.add_parser("remove", help="Remove a rule")
    rules_remove_parser.add_argument("rule_id", type=int)

    rules_enable_parser = rules_sub.add_parser("enable", help="Enable a rule")
    rules_enable_parser.add_argument("rule_id", type=int)

    rules_disable_parser = rules_sub.add_parser("disable", help="Disable a rule")
    rules_disable_parser.add_argument("rule_id", type=int)

    rules_test_parser = rules_sub.add_parser("test", help="Test rules against current activity")

    # status
    subparsers.add_parser("status", help="Show current activity and tracking status")

    # today
    subparsers.add_parser("today", help="Show today’s tracked time")

    # stats
    stats_parser = subparsers.add_parser("stats", help="Show statistics")
    stats_parser.add_argument("--period", choices=["day", "week", "month", "year"], default=None)
    stats_parser.add_argument("--from", dest="from_date", default=None)
    stats_parser.add_argument("--to", dest="to_date", default=None)

    # activity
    activity_parser = subparsers.add_parser("activity", help="Show raw activity samples")
    activity_parser.add_argument("--limit", type=int, default=20)
    activity_parser.add_argument("--date", dest="date_str", default=None)
    activity_parser.add_argument("--from", dest="from_date", default=None)
    activity_parser.add_argument("--to", dest="to_date", default=None)

    # export
    export_parser = subparsers.add_parser("export", help="Export data")
    export_parser.add_argument("--format", choices=["csv", "json"], default="csv")
    export_parser.add_argument("--from", dest="from_date", default=None)
    export_parser.add_argument("--to", dest="to_date", default=None)
    export_parser.add_argument("--output", required=True)
    export_parser.add_argument("--table", choices=["sessions", "activities"], default="sessions")

    # tracking
    tracking_parser = subparsers.add_parser("tracking", help="Pause/resume tracking")
    tracking_sub = tracking_parser.add_subparsers(dest="subcommand")
    tracking_sub.add_parser("pause")
    tracking_sub.add_parser("resume")
    tracking_sub.add_parser("status")

    # daemon
    daemon_parser = subparsers.add_parser("daemon", help="Manage daemon")
    daemon_sub = daemon_parser.add_subparsers(dest="subcommand")
    daemon_start_parser = daemon_sub.add_parser("start")
    daemon_start_parser.add_argument("--foreground", action="store_true")
    daemon_sub.add_parser("stop")
    daemon_sub.add_parser("status")
    daemon_sub.add_parser("install")

    # config
    config_parser = subparsers.add_parser("config", help="View or set configuration")
    config_sub = config_parser.add_subparsers(dest="subcommand")

    config_sub.add_parser("list", help="List settings")
    config_get_parser = config_sub.add_parser("get", help="Get a setting")
    config_get_parser.add_argument("key")

    config_set_parser = config_sub.add_parser("set", help="Set a setting")
    config_set_parser.add_argument("key")
    config_set_parser.add_argument("value")

    # db
    db_parser = subparsers.add_parser("db", help="Database maintenance")
    db_sub = db_parser.add_subparsers(dest="subcommand")
    db_sub.add_parser("prune")
    db_sub.add_parser("backup")

    return parser


def main(argv: Optional[List[str]] = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    if args.command is None:
        parser.print_help()
        return 0

    init_database(DB_PATH)
    ensure_db_permissions(DB_PATH)

    try:
        if args.command == "projects":
            sub = args.subcommand or "list"
            if sub == "list":
                projects_list(args.all)
            elif sub == "add":
                projects_add(args.name, args.color)
            elif sub == "archive":
                projects_archive(args.project_id, 1)
            elif sub == "unarchive":
                projects_archive(args.project_id, 0)
            elif sub == "remove":
                projects_remove(args.project_id)
            else:
                raise CliError("Unknown projects subcommand")
        elif args.command == "rules":
            sub = args.subcommand or "list"
            if sub == "list":
                rules_list(args.project)
            elif sub == "add":
                rules_add(
                    args.project_id,
                    args.rule_type,
                    args.rule_value,
                    args.group,
                    not args.disabled,
                )
            elif sub == "remove":
                rules_remove(args.rule_id)
            elif sub == "enable":
                rules_toggle(args.rule_id, True)
            elif sub == "disable":
                rules_toggle(args.rule_id, False)
            elif sub == "test":
                rules_test()
            else:
                raise CliError("Unknown rules subcommand")
        elif args.command == "status":
            status_show()
        elif args.command == "today":
            today_show()
        elif args.command == "stats":
            stats_show(args.period, args.from_date, args.to_date)
        elif args.command == "activity":
            activity_show(args.limit, args.date_str, args.from_date, args.to_date)
        elif args.command == "export":
            export_data(args.output, args.format, args.from_date, args.to_date, args.table)
        elif args.command == "tracking":
            sub = args.subcommand or "status"
            if sub == "pause":
                tracking_pause()
            elif sub == "resume":
                tracking_resume()
            elif sub == "status":
                tracking_status()
            else:
                raise CliError("Unknown tracking subcommand")
        elif args.command == "daemon":
            sub = args.subcommand or "status"
            if sub == "start":
                daemon_start(args.foreground)
            elif sub == "stop":
                daemon_stop()
            elif sub == "status":
                daemon_status()
            elif sub == "install":
                daemon_install()
            else:
                raise CliError("Unknown daemon subcommand")
        elif args.command == "config":
            sub = args.subcommand or "list"
            if sub == "list":
                config_list()
            elif sub == "get":
                config_get(args.key)
            elif sub == "set":
                config_set(args.key, args.value)
            else:
                raise CliError("Unknown config subcommand")
        elif args.command == "db":
            sub = args.subcommand or "prune"
            if sub == "prune":
                db_prune()
            elif sub == "backup":
                db_backup()
            else:
                raise CliError("Unknown db subcommand")
        else:
            raise CliError("Unknown command")
    except CliError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
