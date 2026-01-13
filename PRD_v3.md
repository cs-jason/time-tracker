# Timemator Clone - Product Requirements Document v3

Document Version: 3.0
Date: January 13, 2026
Status: Updated specification (addresses review issues)
Purpose: Enable an LLM to recreate a CLI-based automatic time tracking tool

---

## Assumptions (Confirmed)

1. First match wins across projects.
   - Projects are evaluated in deterministic order: lowest `project_id` (creation order) first.
   - Rules within a project are evaluated in deterministic order: lowest `rule_id` first.
2. Idle handling: allow a short grace period, but do not count the idle grace time.
   - Idle grace period is 5 minutes (300 seconds).
3. All timestamps are stored in UTC.
   - Display uses local time by default, but storage is UTC.
4. `tt activity` shows raw samples (not aggregated blocks).

---

## Executive Summary

### Product Vision

Build a CLI-based time tracking tool for macOS that passively captures user activity and automatically tracks time based on configurable rules. No GUI app required; all interaction happens through the terminal.

### Key Value Propositions

1. Passive activity capture (apps, windows, files, URLs)
2. Rule-based auto-tracking to projects
3. CLI-first operations and reporting
4. Privacy-first: all data local
5. Lightweight background service

### Scope

In scope:
- Activity timeline capture (raw sampling)
- Auto-tracking rules and session logging
- CLI for stats, rules, projects, and config
- Local SQLite storage
- Optional menu bar indicator

Out of scope:
- Manual start/stop timer
- GUI application
- Task/folder hierarchy
- Billing/invoicing
- iCloud/iOS sync
- Session editing (initially)

---

## Product Overview

### What It Does

A background service that:
1. Monitors active app, window title, file path, and browser URL
2. Records raw activity entries to a local database
3. Evaluates auto-tracking rules against current activity
4. Logs tracked sessions to projects
5. Provides CLI commands to view stats and manage rules

### How It Works (High Level)

- Activity Monitor samples activity every N seconds (default 2).
- Session Manager evaluates rules in deterministic order.
- First matching project wins and starts/continues the session.
- Idle handling pauses/ends sessions after a grace period without counting idle time.

---

## Core Features

### 1. Activity Timeline (Raw Sampling)

Purpose: capture user activity for tracking and diagnostics.

Captured fields (every 1-5 seconds):
- timestamp (UTC ISO 8601, e.g., 2026-01-13T09:15:23Z)
- app_name
- bundle_id
- window_title
- file_path (if detected)
- url (if browser)
- idle (boolean)

Rules for data quality:
- Missing fields are allowed and stored as NULL.
- Rule matching must treat missing fields as non-matches (no crashes).

Idle detection:
- `idle_threshold` seconds with no keyboard/mouse input sets `idle = true`.
- Idle uses monotonic time for reliability.

### 2. Activity Aggregation (Internal)

Purpose: speed up stats and analytics, not shown by default in `tt activity`.

Aggregation rules:
- Consecutive samples merge only if all of these fields match:
  app_name, bundle_id, window_title, file_path, url, idle
- Each block stores start_time, end_time, duration.
- Raw samples remain the source of truth for `tt activity`.

### 3. Auto-Tracking Rules

Rule types:
- app (exact app name or bundle ID)
- app_contains
- window_contains
- window_regex (regex search)
- path_prefix
- path_contains
- url_contains
- url_regex (regex search)

Matching behavior:
- Case-insensitive for plain text comparisons.
- Regex uses search semantics (not match) and respects inline flags like `(?i)`.
- Missing values are treated as non-matches.

Rule combinations:
- Ungrouped rules (group = 0): OR logic.
- Grouped rules (group > 0): AND logic within the group.
- A project matches if any ungrouped rule matches OR any group fully matches.

Project selection:
- Projects evaluated in ascending `project_id` (creation order).
- Rules evaluated in ascending `rule_id`.
- First matching project wins.

### 4. Session Tracking

Behavior:
- If rules match, start or continue a session for the winning project.
- If rules change to a different project, end current and start new.
- If no rules match, apply session grace logic.

Grace periods:
- `session_grace_period` applies to non-matching activity gaps.
- `idle_grace_period` applies to idle time and defaults to 300 seconds.
- Idle grace time is NOT counted if the user remains idle beyond the grace period.

---

## Data Models

### SQLite Schema (UTC timestamps)

```sql
CREATE TABLE activities (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    timestamp TEXT NOT NULL,           -- UTC ISO 8601 (e.g., 2026-01-13T09:15:23Z)
    app_name TEXT,
    bundle_id TEXT,
    window_title TEXT,
    file_path TEXT,
    url TEXT,
    idle INTEGER DEFAULT 0,
    created_at TEXT DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX idx_activities_timestamp ON activities(timestamp);
CREATE INDEX idx_activities_bundle_id ON activities(bundle_id);

CREATE TABLE activity_blocks (
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

CREATE INDEX idx_blocks_start ON activity_blocks(start_time);

CREATE TABLE projects (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT UNIQUE NOT NULL,
    created_at TEXT DEFAULT CURRENT_TIMESTAMP,
    archived INTEGER DEFAULT 0
);

CREATE TABLE rules (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    project_id INTEGER NOT NULL,
    rule_type TEXT NOT NULL,
    rule_value TEXT NOT NULL,
    rule_group INTEGER DEFAULT 0,
    enabled INTEGER DEFAULT 1,
    created_at TEXT DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (project_id) REFERENCES projects(id) ON DELETE CASCADE
);

CREATE TABLE sessions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    project_id INTEGER NOT NULL,
    start_time TEXT NOT NULL,
    end_time TEXT NOT NULL,
    duration INTEGER NOT NULL,
    triggered_by TEXT,
    created_at TEXT DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (project_id) REFERENCES projects(id) ON DELETE CASCADE
);

CREATE INDEX idx_sessions_start ON sessions(start_time);
CREATE INDEX idx_sessions_project ON sessions(project_id);

CREATE TABLE settings (
    key TEXT PRIMARY KEY,
    value TEXT
);
```

SQLite requirements:
- `PRAGMA foreign_keys = ON` on every connection.
- Use WAL mode and a busy timeout for daemon + CLI concurrency.

### Settings Keys

| Key | Default | Description |
|-----|---------|-------------|
| poll_interval | 2 | Seconds between captures |
| idle_threshold | 120 | Seconds before idle is true |
| idle_grace_period | 300 | Seconds of idle allowed without ending session (not counted if exceeded) |
| session_grace_period | 120 | Seconds gap allowed when no rule matches |
| min_session_duration | 60 | Minimum session length to keep |
| retention_days | 90 | Days to keep raw activity data |
| blocks_retention_days | 90 | Days to keep activity blocks |
| sessions_retention_days | 0 | 0 means keep indefinitely |
| week_start | monday | Week boundary for stats output |

Note: `db_path` is a derived read-only value displayed by CLI (default: `~/.tt/tt.db`). It is not stored in settings.

---

## CLI Interface

Command structure:
- `tt <command> [subcommand] [options]`

### `tt status`

Shows current activity and tracking status.
- If idle, show idle state and remaining grace time.
- If tracking, show project, rule, and session duration.

### `tt today`

Shows today's tracked time summary (displayed in local time, stored in UTC).

Example date correction:
- "Tuesday, January 13, 2026"

### `tt stats`

Stats for a time period. Defaults to current week (week starts per `week_start`).

### `tt activity`

Shows raw activity samples only.
- Filters: `--limit`, `--app`, `--date`
- Always reads from `activities`

### `tt projects`

List/add/rename/archive/delete projects.
- Archived projects are excluded from matching and stats.

### `tt rules`

Manage auto-tracking rules.
- Disabled rules are excluded from matching.
- `tt rules test` reports the first matching project and optionally lists other matches with `--all`.

### `tt daemon`

Control background service.
- `install` uses a LaunchAgent (not LaunchDaemon) so UI permissions and foreground app access work.

### `tt config`

View and set configuration values.

---

## Auto-Tracking Logic (Updated)

### Rule Evaluation (Deterministic)

- Only active projects (`archived = 0`) and enabled rules (`enabled = 1`) are evaluated.
- Projects sorted by `project_id` ascending.
- Rules sorted by `rule_id` ascending.
- First project that matches wins.

### Session Management (Idle-Safe)

- Use `activity.timestamp` (UTC) for session timing.
- Use `total_seconds()` when computing gaps.
- When idle begins, start idle grace timer.
- If idle persists beyond `idle_grace_period`, end the session at `last_active_time` (do not count idle grace).

---

## Activity Monitoring (macOS)

Requirements:
- Must run as a LaunchAgent in the user session to read active app/window state.
- Accessibility permission required for window titles.
- Automation permission required for browser URL extraction via AppleScript/ScriptingBridge.
- Screen Recording permission may be required on some macOS versions or browsers.

---

## Technical Architecture

### Directory Structure

`~/.tt/`
- `tt.db` (SQLite)
- `tt.pid` (if using PID file)
- `tt.log`
- `tt.sock` (optional IPC)
- `backups/`

### Daemon Requirements

- Ensure `~/.tt/` exists before opening log/db/pid files.
- Use WAL + busy timeout for concurrency.
- Graceful shutdown ends active session at current activity timestamp.

### Technology Stack

- Python 3.10+
- Click + Rich for CLI
- SQLite for storage
- PyObjC for macOS APIs
- LaunchAgent for background operation

---

## Non-Functional Requirements

Performance targets:
- Daemon CPU usage: < 1% average
- Daemon memory: < 50MB
- CLI response time: < 200ms

Database growth:
- Raw samples at 2s interval can exceed 1M rows/month.
- Expect tens to hundreds of MB depending on usage.
- Use retention policies to bound size.

Privacy & security:
- All data stored locally
- No network requests
- Database permissions 600

Reliability:
- WAL + busy timeout to avoid "database is locked"
- Automatic backups (weekly)
- Graceful shutdown preserves sessions

---

## Implementation Priority

Phase 1 (MVP)
1. SQLite database setup + WAL/foreign_keys
2. Activity monitoring (app + window title)
3. Rule storage/evaluation (deterministic)
4. Session tracking (UTC, idle grace)
5. CLI: `status`, `projects`, `rules add/remove`, `today`

Phase 2 (Enhanced)
6. Browser URL extraction
7. File path detection for IDEs
8. Idle detection
9. CLI: `stats`, `activity`, `rules test`

Phase 3 (Polish)
10. Daemon management (install/start/stop)
11. CLI: `export`, `config`, `db` commands
12. Activity aggregation + pruning
13. Rich formatted output

Phase 4 (Optional)
14. Menu bar item
15. Additional browser support
16. Regex rule enhancements

---

*End of PRD v3*
