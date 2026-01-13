# Timemator Clone - Product Requirements Document v4

> **Document Version:** 4.8
> **Date:** January 13, 2026
> **Status:** Complete Specification
> **Purpose:** Enable an LLM to recreate a CLI-based automatic time tracking tool

---

## Confirmed Assumptions

1. **First match wins across projects.**
   - Projects are evaluated in deterministic order: lowest `project_id` (creation order) first.
   - Within each project, rules are evaluated in this order:
     1. **Ungrouped rules** (`rule_group = 0`) in ascending `rule_id` order (OR logic).
     2. **Grouped rules** by ascending `rule_group` number, then ascending `rule_id` within each group (AND logic within group).
   - This means ungrouped rules always take precedence over grouped rules, regardless of `rule_id`.
2. **Idle handling: allow a short grace period, but do not count the idle grace time.**
   - Idle grace period is 5 minutes (300 seconds).
3. **All timestamps are stored in UTC.**
   - Display uses local time by default, but storage is always UTC ISO 8601.
4. **`tt activity` shows raw samples (not aggregated blocks).**

---

## Executive Summary

### Product Vision

Build a **CLI-based time tracking tool** for macOS that passively captures user activity and automatically tracks time based on configurable rules. No GUI app required—all interaction happens through the terminal.

### Key Value Propositions

1. **Passive Activity Capture**: Records what apps/files/URLs you use throughout the day
2. **Rule-Based Auto-Tracking**: Automatically logs time to projects when rules match
3. **CLI-First**: View stats, configure rules, and manage everything from the terminal
4. **Privacy-First**: All data stored locally
5. **Lightweight**: Runs as a background daemon with minimal resource usage

### Scope

| In Scope | Out of Scope |
|----------|--------------|
| Activity timeline capture (raw sampling) | GUI application |
| Auto-tracking rules and session logging | Manual timer start/stop |
| CLI for stats, rules, projects, and config | Task/folder hierarchy |
| Local SQLite storage | Billing/revenue tracking |
| Menu bar item (optional) | Session editing (initially) |
| | iCloud sync |
| | iOS/Watch apps |

---

## Product Overview

### What It Does

A background service that:

1. **Monitors** the active application, window title, file path, and browser URL
2. **Records** raw activity entries to a local database
3. **Evaluates** auto-tracking rules against current activity
4. **Logs** tracked sessions to projects when rules match
5. **Provides** CLI commands to view stats and manage rules

### How It Works

```
┌─────────────────┐
│  Activity       │
│  Monitor        │──────► Activity Entries (SQLite)
│  (daemon)       │
└────────┬────────┘
         │
         ▼
┌─────────────────┐
│  Rule Engine    │──────► Tracked Time Sessions
└─────────────────┘
         │
         ▼
┌─────────────────┐
│  CLI Interface  │◄────── User queries stats/config
└─────────────────┘
```

- Activity Monitor samples activity every N seconds (default 2).
- Session Manager evaluates rules in deterministic order.
- First matching project wins and starts/continues the session.
- Idle handling pauses/ends sessions after a grace period without counting idle time.

---

## Core Features

### 1. Activity Timeline (Raw Sampling)

**Purpose**: Capture user activity for tracking and diagnostics.

**What Gets Captured** (every 1-5 seconds):

| Field | Description | Example |
|-------|-------------|---------|
| `timestamp` | When captured (UTC ISO 8601) | `2026-01-13T09:15:23Z` |
| `app_name` | Frontmost application | `Visual Studio Code` |
| `bundle_id` | App bundle identifier | `com.microsoft.VSCode` |
| `window_title` | Active window title | `main.py - my-project` |
| `file_path` | Detected file path (if any) | `/Users/jason/code/my-project/main.py` |
| `url` | Browser URL (if browser) | `https://github.com/jason/repo` |
| `idle` | Is user idle? | `false` |

**Data Quality Rules**:
- Missing fields are allowed and stored as NULL.
- Rule matching must treat missing fields as non-matches (no crashes).

**Idle Detection**:
- `idle_threshold` seconds with no keyboard/mouse input sets `idle = true`.
- Idle detection uses monotonic time for reliability.

**Supported Apps for Enhanced Tracking**:

*Browsers (URL extraction):*
- Safari
- Google Chrome, Chrome Canary
- Firefox, Firefox Developer Edition
- Arc Browser
- Brave, Edge, Vivaldi, Opera

*IDEs (file/project detection):*
- VS Code, Cursor
- Xcode
- JetBrains IDEs (IntelliJ, PyCharm, WebStorm, etc.)
- Sublime Text

*Design Tools:*
- Figma, Sketch
- Adobe Creative Suite

### 2. Activity Aggregation (Internal)

**Purpose**: Speed up stats and analytics. Not shown by `tt activity`.

**Aggregation Rules**:
- Consecutive samples merge only if ALL fields match:
  `app_name`, `bundle_id`, `window_title`, `file_path`, `url`, `idle`
- Each block stores `start_time`, `end_time`, `duration`.
- Raw samples remain the source of truth for `tt activity`.

### 3. Auto-Tracking Rules

**Rule Types**:

| Rule Type | Matches On | Example |
|-----------|------------|---------|
| `app` | Bundle ID or app name (exact) | `com.microsoft.VSCode` |
| `app_contains` | App name contains | `Code` |
| `window_contains` | Window title contains | `my-project` |
| `window_regex` | Window title regex (search) | `.*\.tsx? - .*` |
| `path_prefix` | File path starts with | `/Users/jason/code/client-a/` |
| `path_contains` | File path contains | `client-a` |
| `url_contains` | URL contains | `github.com/client-a` |
| `url_regex` | URL regex (search) | `https://.*\.atlassian\.net/.*` |

**Matching Behavior**:
- **Case-insensitive** for plain text comparisons (`app`, `app_contains`, `window_contains`, `path_prefix`, `path_contains`, `url_contains`).
- **Regex uses search semantics** (not match), case-sensitive by default. Use inline flag `(?i)` for case-insensitivity.
- **Missing values are treated as non-matches** (never crash on NULL).

**Rule Combinations**:
- Ungrouped rules (`group = 0`): OR logic.
- Grouped rules (`group > 0`): AND logic within the group.
- A project matches if any ungrouped rule matches OR any group fully matches.

**Project Selection (Deterministic)**:
- Projects evaluated in ascending `project_id` (creation order).
- Within each project:
  1. Ungrouped rules (`group = 0`) checked first, in ascending `rule_id` order.
  2. Grouped rules checked by ascending `group` number, then `rule_id` within group.
- First matching project wins (ungrouped rules have priority over grouped rules).

### 4. Session Tracking

**Behavior**:
- If rules match, start or continue a session for the winning project.
- If rules change to a different project, end current and start new.
- If no rules match, apply session grace logic.

**Grace Periods**:
- `session_grace_period`: Applies to non-matching activity gaps (default 120s).
- `idle_grace_period`: Applies to idle time (default 300s).
- **Idle grace time is NOT counted** if the user remains idle beyond the grace period.

---

## Data Models

### Database Schema (SQLite)

```sql
-- Raw activity entries (high frequency)
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

-- Aggregated activity blocks (for efficient querying)
CREATE TABLE activity_blocks (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    start_time TEXT NOT NULL,
    end_time TEXT NOT NULL,
    duration INTEGER NOT NULL,         -- Seconds
    app_name TEXT,
    bundle_id TEXT,
    window_title TEXT,
    file_path TEXT,
    url TEXT,
    idle INTEGER DEFAULT 0
);

CREATE INDEX idx_blocks_start ON activity_blocks(start_time);

-- Projects for auto-tracking
CREATE TABLE projects (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT UNIQUE NOT NULL,
    color TEXT DEFAULT '#808080',      -- Hex color for display
    archived INTEGER DEFAULT 0,
    created_at TEXT DEFAULT CURRENT_TIMESTAMP
);

-- Auto-tracking rules
CREATE TABLE rules (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    project_id INTEGER NOT NULL,
    rule_type TEXT NOT NULL,           -- app, window_contains, path_prefix, etc.
    rule_value TEXT NOT NULL,          -- The pattern to match
    rule_group INTEGER DEFAULT 0,      -- 0 = OR with others, >0 = AND within group
    enabled INTEGER DEFAULT 1,
    created_at TEXT DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (project_id) REFERENCES projects(id) ON DELETE CASCADE
);

-- Tracked time sessions
CREATE TABLE sessions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    project_id INTEGER NOT NULL,
    start_time TEXT NOT NULL,
    end_time TEXT NOT NULL,
    duration INTEGER NOT NULL,         -- Seconds
    triggered_by TEXT,                 -- Rule description
    created_at TEXT DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (project_id) REFERENCES projects(id) ON DELETE CASCADE
);

CREATE INDEX idx_sessions_start ON sessions(start_time);
CREATE INDEX idx_sessions_project ON sessions(project_id);
CREATE INDEX idx_rules_project ON rules(project_id);

-- App settings
CREATE TABLE settings (
    key TEXT PRIMARY KEY,
    value TEXT
);
```

**SQLite Requirements**:
- `PRAGMA foreign_keys = ON` on every connection.
- Use WAL mode and a busy timeout (e.g., 5000ms) for daemon + CLI concurrency.

**Timestamp Column Notes**:
- **Business timestamps** (`timestamp`, `start_time`, `end_time`): Stored as UTC ISO 8601 with `Z` suffix (e.g., `2026-01-13T09:15:23Z`). Used for queries, filtering, and display.
- **Metadata timestamps** (`created_at`): Uses SQLite `CURRENT_TIMESTAMP` (e.g., `2026-01-13 09:15:23`). This is internal metadata only—never used for business logic, filtering, or display. Do not parse with `parse_utc_timestamp()`.

### Settings Keys

| Key | Default | Description |
|-----|---------|-------------|
| `poll_interval` | `2` | Seconds between activity captures |
| `idle_threshold` | `120` | Seconds before marking as idle |
| `idle_grace_period` | `300` | Seconds of idle allowed without ending session (not counted if exceeded) |
| `session_grace_period` | `120` | Seconds gap allowed when no rule matches |
| `min_session_duration` | `60` | Minimum session length to keep |
| `retention_days` | `90` | Days to keep raw activity data |
| `blocks_retention_days` | `90` | Days to keep activity blocks |
| `sessions_retention_days` | `0` | 0 means keep indefinitely |
| `week_start` | `monday` | Week boundary for stats output |
| `tracking_paused` | `0` | 1 = tracking paused, 0 = tracking active |
| `tracking_paused_at` | `NULL` | UTC ISO 8601 timestamp when pause was activated (NULL if not paused) |

**Note**: `db_path` is a derived read-only value displayed by CLI (default: `~/.tt/tt.db`). It is not stored in settings.

### Time Handling

**Storage**: All timestamps are stored in UTC ISO 8601 format with `Z` suffix (e.g., `2026-01-13T09:15:23Z`).

**Display**: CLI commands display times in the user's local timezone.

**Day Boundaries**: When filtering by date (e.g., `--date 2026-01-13`), the day boundary is interpreted in **local time**:
- A "day" spans from `00:00:00` to `23:59:59` in the user's local timezone.
- This is converted to UTC for database queries.
- Example: In GMT+8, `--date 2026-01-13` queries UTC range `2026-01-12T16:00:00Z` to `2026-01-13T15:59:59Z`.

**Week Boundaries**: Determined by `week_start` setting (default: `monday`).
- "This week" starts at `00:00:00` local time on the configured start day.
- Week runs for 7 days until the next start day.

### Activity Block Duration Semantics

Activity blocks store aggregated activity for efficient querying.

**Duration Calculation**:
- `start_time`: Timestamp of the first sample in the block.
- `end_time`: Timestamp of the last sample in the block.
- `duration`: `round((end_time - start_time).total_seconds())` — uses Python's `round()` for nearest integer (not `int()` which truncates).

**Boundary Behavior**:
- Duration is **inclusive** of both start and end samples.
- For a single sample, `start_time == end_time` and `duration = 0`.
- The actual time spent may exceed `duration` by up to one `poll_interval` (the time until the next sample that broke the block).

**Example**: With `poll_interval = 2`:
- Samples at 09:00:00, 09:00:02, 09:00:04 (same context) → Block with duration = 4 seconds.
- True activity time is ~6 seconds (until 09:00:06 when context changed), but we only record sampled points.

---

## CLI Interface

### Command Structure

```
tt <command> [subcommand] [options]
```

### Initialization Requirement

**Important**: All CLI commands that access the database MUST call `init_database()` before any DB operations. This ensures the schema and default settings exist, even if the daemon has never been started.

```python
# At the start of any CLI command that touches the database:
from tt_db import init_database, DB_PATH  # Shared DB module (no macOS deps)

def cli_command():
    init_database(DB_PATH)  # Safe to call multiple times (uses IF NOT EXISTS)
    # ... rest of command
```

This applies to commands like `tt projects add`, `tt rules add`, `tt config`, `tt rules test`, etc. Without this, CLI-first usage (before daemon runs) would fail with "table not found" errors.

**Module Structure Note**: Database code (`init_database`, `get_db_connection`, `Config`, `load_config`, etc.) should live in a shared `tt_db.py` module that has no macOS-specific dependencies. The daemon (`tt_daemon.py`) imports from `tt_db` and adds macOS-only code (PyObjC/AppKit for activity monitoring). This allows CLI commands to initialize the database without pulling in macOS dependencies that would fail on other platforms or in test environments.

### Commands Overview

| Command | Description |
|---------|-------------|
| `tt status` | Show current activity and tracking status |
| `tt today` | Show today's tracked time summary |
| `tt stats` | Show statistics for a time period |
| `tt activity` | View raw activity samples |
| `tt projects` | List/manage projects |
| `tt rules` | List/manage auto-tracking rules |
| `tt tracking` | Pause/resume automatic tracking |
| `tt daemon` | Control background service |
| `tt config` | View/set configuration |
| `tt export` | Export data to CSV/JSON |
| `tt db` | Database maintenance commands |

---

### `tt status`

Show what's currently being tracked.

```bash
$ tt status

Current Activity
────────────────────────────────────────────────────
App:      Visual Studio Code
Window:   main.py - my-project
Path:     /Users/jason/code/my-project/main.py
Since:    2 minutes ago

Auto-Tracking
────────────────────────────────────────────────────
Project:  My Project
Rule:     path_prefix: /Users/jason/code/my-project
Duration: 00:47:23 (this session)
```

When idle:
```bash
$ tt status

Current Activity
────────────────────────────────────────────────────
Status:   Idle (3m 24s)
Last:     Visual Studio Code - main.py

Auto-Tracking
────────────────────────────────────────────────────
Project:  My Project (paused - idle)
Grace:    1m 36s remaining
Session:  00:47:23 so far
```

When not tracking:
```bash
$ tt status

Current Activity
────────────────────────────────────────────────────
App:      Safari
Window:   Reddit - Pair programming tips
URL:      https://reddit.com/r/programming/...
Since:    5 minutes ago

Auto-Tracking
────────────────────────────────────────────────────
Not tracking (no rules match)
```

---

### `tt today`

Summary of today's tracked time (displayed in local time).

```bash
$ tt today

Today: Tuesday, January 13, 2026
────────────────────────────────────────────────────
Project                    Time        Sessions
────────────────────────────────────────────────────
Wonderstruck Website       02:34:12    3
Client A Redesign          01:15:45    2
Internal Tools             00:42:08    1
────────────────────────────────────────────────────
Total Tracked              04:32:05    6
Total Active               06:15:33
Untracked                  01:43:28
Idle                       00:45:00
```

**Summary Row Definitions**:
- **Total Tracked**: Sum of all session durations for the day.
- **Total Active**: Time with `idle = false` in raw activity samples (non-idle computer use).
- **Untracked**: `Total Active - Total Tracked` (active time that didn't match any rules).
- **Idle**: Time with `idle = true` in raw activity samples (no keyboard/mouse input).

**Sample-to-Time Calculation**:
- Each raw activity sample represents approximately `poll_interval` seconds of time.
- **Total Active** = `(count of samples where idle = 0) × poll_interval`
- **Idle** = `(count of samples where idle = 1) × poll_interval`
- This is an approximation—actual time may vary by up to `poll_interval` at boundaries.

**Example** (with `poll_interval = 2`):
- 450 non-idle samples → 900 seconds (15 minutes) of active time.
- 30 idle samples → 60 seconds (1 minute) of idle time.

**Historical Accuracy Note**: If `poll_interval` is changed, totals computed for periods before the change will be incorrect (old samples used a different interval). Two approaches to handle this:
1. **Store effective interval per sample**: Add `poll_interval INTEGER` column to `activities` table, populated at capture time. Use stored value for calculations.
2. **Compute from timestamps**: For accurate historical totals, compute duration as `(last_timestamp - first_timestamp)` for each day/period instead of `count × interval`.

For simplicity, the MVP can use the current `poll_interval` setting and document that changing it affects historical accuracy. Production implementations should use approach 1 or 2.

**Note**: `Total Active + Idle` approximates total time the daemon was running, though gaps may exist if the daemon was stopped.

---

### `tt stats`

Detailed statistics for a time period.

```bash
$ tt stats [--period <day|week|month|year>] [--from <date>] [--to <date>]

# Examples:
$ tt stats                    # This week (default)
$ tt stats --period month     # This month
$ tt stats --from 2026-01-01  # Custom range
```

**Output:**

```bash
$ tt stats --period week

Week of January 5 - January 11, 2026 (Mon-Sun)
════════════════════════════════════════════════════

By Project
────────────────────────────────────────────────────
Project                    Hours      %     ████████
────────────────────────────────────────────────────
Wonderstruck Website       12.5h    38%    ████████████
Client A Redesign           8.2h    25%    ████████
EunBin PM Course            6.0h    18%    ██████
Internal Work               4.3h    13%    ████
(Untracked)                 2.1h     6%    ██
────────────────────────────────────────────────────
Total Active               33.1h   100%
(Idle)                      4.2h

By Day
────────────────────────────────────────────────────
Mon   ████████████████████░░░░  5.2h
Tue   ██████████████████████░░  6.1h
Wed   ████████████████░░░░░░░░  4.3h
Thu   ██████████████████████░░  5.8h
Fri   ████████████████████████  6.4h
Sat   ██████░░░░░░░░░░░░░░░░░░  2.1h
Sun   ████████░░░░░░░░░░░░░░░░  3.2h

Top Apps (All Activity)
────────────────────────────────────────────────────
Visual Studio Code         14.2h    43%
Figma                       6.8h    21%
Safari                      4.1h    12%
Slack                       3.2h    10%
Terminal                    2.5h     8%
Other                       2.3h     7%
```

---

### `tt activity`

View raw activity samples (not aggregated blocks).

```bash
$ tt activity [--limit <n>] [--app <name>] [--date <date>]

# Examples:
$ tt activity                    # Last 20 entries
$ tt activity --limit 50         # Last 50 entries
$ tt activity --app "VS Code"    # Filter by app
$ tt activity --date 2026-01-10  # Specific date
```

**Output:**

```bash
$ tt activity --limit 10

Activity Samples (Today)
────────────────────────────────────────────────────
Time      App               Window/URL
────────────────────────────────────────────────────
09:15:23  VS Code           main.py - my-project
09:15:25  VS Code           main.py - my-project
09:15:27  VS Code           main.py - my-project
09:47:02  Safari            Stack Overflow - Python async
09:47:04  Safari            Stack Overflow - Python async
09:52:15  VS Code           api.py - my-project
09:52:17  VS Code           api.py - my-project
10:34:08  Slack             #wonderstruck-general
10:34:10  Slack             #wonderstruck-general
10:41:33  Safari            GitHub - PR #234
```

---

### `tt projects`

Manage projects.

```bash
# List all projects
$ tt projects

Projects
────────────────────────────────────────────────────
ID  Name                     Rules  Tracked (week)
────────────────────────────────────────────────────
1   Wonderstruck Website     3      12.5h
2   Client A Redesign        2       8.2h
3   EunBin PM Course         2       6.0h
4   Internal Work            1       4.3h

# Add new project
$ tt projects add "New Client Project"
✓ Created project: New Client Project (ID: 5)

# Rename project
$ tt projects rename 5 "Client B Website"
✓ Renamed project 5 to: Client B Website

# Archive project (keeps data, stops tracking)
$ tt projects archive 5
✓ Archived project: Client B Website

# Delete project (removes all associated data via CASCADE)
$ tt projects delete 5 --confirm
✓ Deleted project and all associated data
```

**Note**: Archived projects are excluded from rule matching and stats.

---

### `tt rules`

Manage auto-tracking rules.

```bash
# List all rules
$ tt rules

Auto-Tracking Rules
════════════════════════════════════════════════════

Wonderstruck Website (Project ID: 1)
────────────────────────────────────────────────────
ID  Type            Value                      Group  Enabled
────────────────────────────────────────────────────
1   path_prefix     /Users/jason/code/ws/      -      ✓
2   url_contains    github.com/wonderstruck    -      ✓
3   window_contains wonderstruck               -      ✓

Client A Redesign (Project ID: 2)
────────────────────────────────────────────────────
ID  Type            Value                      Group  Enabled
────────────────────────────────────────────────────
4   path_prefix     /Users/jason/code/client-a -      ✓
5   url_contains    figma.com/file/abc123      -      ✓

# Add a rule
$ tt rules add <project_id> <rule_type> <value> [--group <n>]

# Examples:
$ tt rules add 1 path_prefix "/Users/jason/code/wonderstruck/"
✓ Added rule to Wonderstruck Website

$ tt rules add 1 url_contains "notion.so/wonderstruck"
✓ Added rule to Wonderstruck Website

$ tt rules add 2 app "Figma" --group 1
$ tt rules add 2 window_contains "Client A" --group 1
✓ Added rules to Client A Redesign (AND group 1)

# Remove a rule
$ tt rules remove <rule_id>
$ tt rules remove 5
✓ Removed rule 5

# Disable/enable a rule
$ tt rules disable 3
✓ Disabled rule 3

$ tt rules enable 3
✓ Enabled rule 3

# Test what rules match current activity
$ tt rules test
Current activity matches:
  → Wonderstruck Website (rule 1: path_prefix)

$ tt rules test --all
Current activity matches:
  → Wonderstruck Website (rule 1: path_prefix) [WINNER]
  → Internal Work (rule 7: app_contains)
```

**Rule Types Reference:**

```bash
$ tt rules types

Available Rule Types
────────────────────────────────────────────────────
Type             Description                Example
────────────────────────────────────────────────────
app              Exact app name/bundle ID   "com.microsoft.VSCode"
app_contains     App name contains          "Code"
window_contains  Window title contains      "my-project"
window_regex     Window title regex         ".*\.py - .*"
path_prefix      File path starts with      "/Users/jason/code/proj/"
path_contains    File path contains         "client-a"
url_contains     URL contains               "github.com/myorg"
url_regex        URL regex match            ".*\.atlassian\.net.*"

Matching:
  - Text rules: case-insensitive
  - Regex rules: case-sensitive, use (?i) for insensitivity
  - Missing values: never match (safe)
  - Invalid regex: validated on `tt rules add`; invalid patterns are rejected with error message. If somehow stored, they log a warning and never match.

Group Logic:
  - Rules with group=0 (default): OR logic (any match triggers)
  - Rules with same group>0: AND logic (all must match)
```

---

### `tt tracking`

Pause or resume automatic tracking.

```bash
# Check current tracking status
$ tt tracking status
Tracking: Active
Current session: Wonderstruck Website (00:32:15)

$ tt tracking status
Tracking: Paused
Paused since: 2026-01-13 14:23:00 (local time)

# Pause tracking (ends session at last_active_time, not pause time)
$ tt tracking pause
✓ Tracking paused
✓ Ended session: Wonderstruck Website (00:32:15)

# Resume tracking
$ tt tracking resume
✓ Tracking resumed
```

**Behavior**:
- `pause`:
  1. Sets `tracking_paused = 1` and `tracking_paused_at = <current UTC timestamp>` in settings.
  2. Sends IPC signal to daemon via Unix socket (`~/.tt/tt.sock`) to end the session immediately (without waiting for next poll). Note: "immediately" means the daemon processes the end right away, but the session's `end_time` is set to `last_active_time` for accurate billing.
  3. Daemon ends any active session with `end_time = last_active_time` (accurate billing—doesn't count time between last activity and pause).
  4. Activity sampling continues (raw data is still recorded).
- `resume`: Sets `tracking_paused = 0` and clears `tracking_paused_at`. Rule evaluation resumes on next activity sample.
- `status`: Shows whether tracking is active or paused, current session info if active, and "Paused since" timestamp if paused. The `tracking_paused_at` value is stored in UTC but converted to local time for display.

**IPC Protocol**:
- Daemon listens on Unix socket `~/.tt/tt.sock` for commands.
- `pause` command: CLI sends `PAUSE\n`, daemon responds `OK\n` after ending session (with `end_time = last_active_time`).
- `resume` command: CLI sends `RESUME\n`, daemon responds `OK\n`.
- If socket unavailable (daemon not running), CLI still sets settings flags for when daemon restarts.

**Note**: This is not a manual timer. It simply disables automatic rule-based tracking while paused.

---

### `tt daemon`

Control the background monitoring service.

```bash
# Start the daemon (backgrounds itself)
$ tt daemon start
✓ Daemon started (PID: 12345)

# Start in foreground (for LaunchAgent use)
$ tt daemon start --foreground
[2026-01-13 09:15:23] Started monitoring
...

# Stop the daemon (also unloads LaunchAgent if installed)
$ tt daemon stop
✓ Unloaded LaunchAgent (KeepAlive disabled)
✓ Daemon stopped

# Stop temporarily (keeps LaunchAgent, will restart on next login)
$ tt daemon stop --temporary
✓ Daemon stopped (will restart on login)

# Restart the daemon
$ tt daemon restart
✓ Daemon restarted (PID: 12346)

# Check daemon status
$ tt daemon status
Daemon Status: Running
PID: 12345
Uptime: 4 hours, 23 minutes
Activities captured: 2,847
Active tracking: Wonderstruck Website (00:32:15)

# View daemon logs
$ tt daemon logs [--follow]
[2026-01-13 09:15:23] Started monitoring
[2026-01-13 09:15:25] Captured: VS Code - main.py
[2026-01-13 09:15:25] Rule match: Wonderstruck Website (path_prefix: /Users/jason/code/ws/)
[2026-01-13 09:15:25] Started session for Wonderstruck Website
...

# Install as LaunchAgent (start on login)
$ tt daemon install
✓ Installed LaunchAgent at ~/Library/LaunchAgents/com.tt.daemon.plist
✓ Daemon started

# Remove from LaunchAgents
$ tt daemon uninstall
✓ Stopped daemon
✓ Removed LaunchAgent

# Run maintenance tasks (handles LaunchAgent lifecycle)
$ tt daemon maintenance vacuum
✓ Unloaded LaunchAgent
✓ Running vacuum...
✓ Vacuum complete
✓ Reloaded LaunchAgent

$ tt daemon maintenance prune
✓ Unloaded LaunchAgent
✓ Running prune...
✓ Removed 847,231 old activity records
✓ Reloaded LaunchAgent
```

**Flags**:
- `--foreground`: Run in foreground instead of daemonizing. Used by LaunchAgent.
- `--temporary` (for `stop`): Stops daemon but keeps LaunchAgent loaded. Daemon will restart on next login or if launchd restarts it.

**Subcommands**:
- `maintenance <vacuum|prune>`: Safely runs database maintenance by temporarily unloading the LaunchAgent (if installed) to prevent KeepAlive conflicts.

**LaunchAgent Behavior**:
- `tt daemon stop`: Unloads LaunchAgent (disables KeepAlive), then stops daemon. Daemon won't restart until `tt daemon start` or `tt daemon install`.
- `tt daemon stop --temporary`: Only sends SIGTERM. With KeepAlive, launchd may restart daemon immediately.
- `tt daemon uninstall`: Unloads and removes LaunchAgent plist completely.

**Note**: Uses LaunchAgent (not LaunchDaemon) so the daemon runs in the user session with proper UI/Accessibility permissions.

---

### `tt config`

View and modify settings.

```bash
# View all settings
$ tt config

Configuration
────────────────────────────────────────────────────
poll_interval           2        Seconds between captures
idle_threshold          120      Seconds before idle
idle_grace_period       300      Idle grace (not counted if exceeded)
session_grace_period    120      Max gap within session
min_session_duration    60       Min session to keep
retention_days          90       Days to keep activity data
blocks_retention_days   90       Days to keep activity blocks
sessions_retention_days 0        Days to keep sessions (0=forever)
week_start              monday   Week boundary for stats
tracking_paused         0        Tracking active (1=paused)
tracking_paused_at      -        Pause timestamp (if paused)
db_path                 ~/.tt/tt.db (read-only)

# Get specific setting
$ tt config get idle_threshold
120

# Set a value
$ tt config set idle_threshold 180
✓ Set idle_threshold = 180

# Reset to default
$ tt config reset idle_threshold
✓ Reset idle_threshold to default (120)

# Show config directory
$ tt config path
~/.tt/
```

---

### Additional Utility Commands

```bash
# Export data
$ tt export [--format csv|json] [--period day|week|month|year] [--from <date>] [--to <date>] [--output <file>]
$ tt export --format csv --from 2026-01-01 --to 2026-01-31 --output january.csv
✓ Exported 847 sessions to january.csv

$ tt export --format json --period week --output this-week.json
✓ Exported 142 sessions to this-week.json

# Database maintenance (requires exclusive access - see note below)
$ tt daemon maintenance vacuum   # Unloads LaunchAgent, runs vacuum, reloads
$ tt daemon maintenance prune    # Unloads LaunchAgent, runs prune, reloads
$ tt db backup           # Create WAL-safe backup to ~/.tt/backups/
✓ Backup created: ~/.tt/backups/tt_2026-01-13_143000.db (47.3 MB)

$ tt db stats            # Show database size and counts (safe while daemon runs)

Database Stats
────────────────────────────────────────────────────
Database size:     47.3 MB
Activities:        1,247,832 rows
Activity blocks:   42,156 rows
Sessions:          1,847 rows
Projects:          12
Rules:             34

# Version and help
$ tt --version
tt 1.0.0

$ tt --help
$ tt <command> --help
```

**Note on Maintenance Commands**:
- `tt daemon maintenance <cmd>` handles the LaunchAgent lifecycle automatically:
  1. Unloads the LaunchAgent (prevents KeepAlive from restarting)
  2. Waits for daemon to stop
  3. Runs the maintenance command
  4. Reloads the LaunchAgent
- Direct `tt db vacuum` / `tt db prune` will fail with "database is locked" if the daemon is running with KeepAlive (launchd will restart it immediately after `tt daemon stop`).
- `tt db backup` uses SQLite's online backup API (`sqlite3_backup` / Python's `conn.backup()`), which is safe with WAL mode and concurrent writes. It creates a consistent snapshot without requiring exclusive access. Note: `VACUUM INTO` requires exclusive access and should only be used when the daemon is stopped.
- `tt db stats` is read-safe and can run while the daemon is active.

---

## Menu Bar Item (Optional)

Lower priority feature—a minimal status indicator.

### Display Options

```
┌─────────────────────────┐
│ ● Wonderstruck  00:32   │  (Tracking: project name + duration)
└─────────────────────────┘

┌──────────┐
│ ○ --:--  │  (Not tracking)
└──────────┘

┌──────────┐
│ ◐ Idle   │  (Idle detected)
└──────────┘
```

### Click Menu

```
┌─────────────────────────────┐
│ ● Tracking: Wonderstruck    │
│   00:32:15 this session     │
├─────────────────────────────┤
│ Today: 4h 32m tracked       │
├─────────────────────────────┤
│ Open Terminal...            │
│ ─────────────────────────── │
│ Pause Tracking              │
│ ─────────────────────────── │
│ Quit                        │
└─────────────────────────────┘
```

**Pause Tracking Behavior**:
- "Pause Tracking" temporarily disables all rule evaluation (no rules match while paused).
- Activity capture continues (raw samples are still recorded).
- This is **not** a manual timer—it simply prevents automatic session tracking.
- Consistent with "Manual timer start/stop" being out of scope.
- Resume via "Resume Tracking" menu item.

**Pause State Model**:
- Pause state is stored in the `settings` table with key `tracking_paused` (value `1` or `0`).
- Pause timestamp is stored with key `tracking_paused_at` (UTC ISO 8601 timestamp).
- When paused (`tracking_paused = 1`):
  - `evaluate_rules()` returns `None` without checking any rules.
  - Any active session ends at `last_active_time` (accurate billing—don't count time between last activity and pause).
  - Raw activity samples continue to be recorded.
- CLI command: `tt tracking pause` / `tt tracking resume` / `tt tracking status`
- IPC: Menu bar and CLI send commands via Unix socket (`~/.tt/tt.sock`). Daemon receives command and ends session with `end_time = last_active_time` (accurate billing—doesn't count time between last activity and pause command).

```python
def evaluate_rules(activity: Activity) -> Optional[RuleMatch]:
    # Check if tracking is paused
    if is_tracking_paused():
        return None
    # ... rest of evaluation
```

### Implementation

- Use `rumps` (Python) for menu bar integration
- Communicates with daemon via Unix socket or reads settings table directly
- Updates every few seconds when tracking

---

## Auto-Tracking Logic (Implementation)

### Rule Evaluation (Deterministic, Null-Safe)

```python
import re
import logging
from dataclasses import dataclass
from typing import Optional, Tuple, List, Dict, Set
from collections import defaultdict

# Track which rules have already logged invalid regex warnings (avoid log spam)
_warned_invalid_regex_rules: Set[int] = set()

@dataclass
class RuleMatch:
    """Result of rule evaluation - includes both project and the winning rule."""
    project: Project
    rule: Rule
    rule_description: str  # e.g., "path_prefix: /Users/jason/code/ws/"

def is_tracking_paused() -> bool:
    """Check if tracking is paused via settings."""
    with get_db_connection() as conn:
        row = conn.execute(
            "SELECT value FROM settings WHERE key = 'tracking_paused'"
        ).fetchone()
        # Handle both string and int values from SQLite
        return row is not None and str(row['value']) == '1'

def evaluate_rules(activity: Activity) -> Optional[RuleMatch]:
    """
    Returns the matching project and rule, or None if no rules match.

    Evaluation order (deterministic):
    1. Check if tracking is paused (return None if so).
    2. Projects are evaluated in ascending project_id order.
    3. Within each project, rules are evaluated in ascending rule_id order.
    4. Ungrouped rules (group=0) are checked first in rule_id order.
    5. Grouped rules are checked by group_id order, then rule_id within group.
    6. First match wins and returns immediately.
    """
    # Check if tracking is paused
    if is_tracking_paused():
        return None

    # Only consider active projects (ORDER BY id ASC, archived = 0)
    for project in get_active_projects():
        match = evaluate_project_rules(project, activity)
        if match:
            return match
    return None

def evaluate_project_rules(project: Project, activity: Activity) -> Optional[RuleMatch]:
    """
    Evaluate all rules for a single project.
    Returns RuleMatch if project matches, None otherwise.
    """
    # Get enabled rules sorted by rule_id (ORDER BY id ASC, enabled = 1)
    rules = get_enabled_rules(project.id)

    # Separate ungrouped and grouped rules
    ungrouped: List[Rule] = []
    groups: Dict[int, List[Rule]] = defaultdict(list)

    for rule in rules:
        if rule.rule_group == 0:
            ungrouped.append(rule)
        else:
            groups[rule.rule_group].append(rule)

    # Check ungrouped rules first (OR logic) - already in rule_id order
    for rule in ungrouped:
        if rule_matches(rule, activity):
            return RuleMatch(
                project=project,
                rule=rule,
                rule_description=f"{rule.rule_type}: {rule.rule_value}"
            )

    # Check grouped rules (AND logic within group)
    # Groups are checked in group_id order
    for group_id in sorted(groups.keys()):
        group_rules = groups[group_id]  # Already in rule_id order
        if all(rule_matches(r, activity) for r in group_rules):
            # Return the first rule in the group as the "trigger"
            first_rule = group_rules[0]
            return RuleMatch(
                project=project,
                rule=first_rule,
                rule_description=f"group {group_id} ({len(group_rules)} rules)"
            )

    return None

def evaluate_all_rules(activity: Activity) -> List[RuleMatch]:
    """
    Returns all matching projects with their matching rules/groups.
    Used by `tt rules test --all` to show all potential matches.

    Returns one entry per matching ungrouped rule, one entry per matching group.
    Groups are represented by their first rule (all rules in group matched).
    First match in list is the winner that would be used for tracking.
    """
    matches: List[RuleMatch] = []
    for project in get_active_projects():
        project_matches = get_all_matching_rules(project, activity)
        matches.extend(project_matches)
    return matches

def get_all_matching_rules(project: Project, activity: Activity) -> List[RuleMatch]:
    """
    Get all matching rules/groups for a single project.
    Returns one RuleMatch per matching ungrouped rule, one per matching group.
    Groups are represented by their first rule (indicates all rules in group matched).
    """
    matches: List[RuleMatch] = []
    rules = get_enabled_rules(project.id)

    # Separate ungrouped and grouped rules
    ungrouped: List[Rule] = []
    groups: Dict[int, List[Rule]] = defaultdict(list)

    for rule in rules:
        if rule.rule_group == 0:
            ungrouped.append(rule)
        else:
            groups[rule.rule_group].append(rule)

    # Check all ungrouped rules (OR logic)
    for rule in ungrouped:
        if rule_matches(rule, activity):
            matches.append(RuleMatch(
                project=project,
                rule=rule,
                rule_description=f"{rule.rule_type}: {rule.rule_value}"
            ))

    # Check all grouped rules (AND logic within group)
    for group_id in sorted(groups.keys()):
        group_rules = groups[group_id]
        if all(rule_matches(r, activity) for r in group_rules):
            first_rule = group_rules[0]
            matches.append(RuleMatch(
                project=project,
                rule=first_rule,
                rule_description=f"group {group_id} ({len(group_rules)} rules)"
            ))

    return matches


def rule_matches(rule: Rule, activity: Activity) -> bool:
    """
    Check if a single rule matches the current activity.
    Missing values are treated as non-matches (safe).
    Text comparisons are case-insensitive.
    Regex uses search semantics (not match), case-sensitive by default.
    """
    value = rule.rule_value.lower()

    match rule.rule_type:
        case "app":
            # Exact match on app_name or bundle_id
            if activity.app_name and value == activity.app_name.lower():
                return True
            if activity.bundle_id and value == activity.bundle_id.lower():
                return True
            return False

        case "app_contains":
            if activity.app_name is None:
                return False
            return value in activity.app_name.lower()

        case "window_contains":
            if activity.window_title is None:
                return False
            return value in activity.window_title.lower()

        case "window_regex":
            if activity.window_title is None:
                return False
            # Use search (not match), case-sensitive by default
            # Catch invalid regex patterns to avoid crashing daemon
            try:
                return re.search(rule.rule_value, activity.window_title) is not None
            except re.error:
                # Invalid regex - log warning once per rule (avoid log spam)
                if rule.id not in _warned_invalid_regex_rules:
                    _warned_invalid_regex_rules.add(rule.id)
                    logging.warning(f"Invalid regex in rule {rule.id}: {rule.rule_value}")
                return False

        case "path_prefix":
            if activity.file_path is None:
                return False
            return activity.file_path.lower().startswith(value)

        case "path_contains":
            if activity.file_path is None:
                return False
            return value in activity.file_path.lower()

        case "url_contains":
            if activity.url is None:
                return False
            return value in activity.url.lower()

        case "url_regex":
            if activity.url is None:
                return False
            # Use search (not match), case-sensitive by default
            # Catch invalid regex patterns to avoid crashing daemon
            try:
                return re.search(rule.rule_value, activity.url) is not None
            except re.error:
                # Invalid regex - log warning once per rule (avoid log spam)
                if rule.id not in _warned_invalid_regex_rules:
                    _warned_invalid_regex_rules.add(rule.id)
                    logging.warning(f"Invalid regex in rule {rule.id}: {rule.rule_value}")
                return False

    return False
```

### Session Management (Idle-Safe, UTC)

```python
from datetime import datetime, timedelta
from typing import Optional
import sqlite3

class SessionManager:
    def __init__(self, config: Config, db_path: Path):
        self.config = config
        self.db_path = db_path
        self.current_session: Optional[Session] = None
        self.last_active_time: Optional[datetime] = None
        self.idle_start_time: Optional[datetime] = None

    def process_activity(self, activity: Activity):
        """
        Process a single activity sample.
        Uses activity.timestamp (UTC) for all timing.
        Handles pause state: ends session immediately when paused.
        """
        timestamp = activity.timestamp  # UTC datetime

        # Check if tracking is paused - end session immediately if so
        if is_tracking_paused():
            if self.current_session:
                # End session at last active time (don't count paused time)
                end_time = self.last_active_time or timestamp
                self._end_session(end_time)
            return  # Skip all rule evaluation while paused

        rule_match = evaluate_rules(activity)  # Returns RuleMatch or None

        if activity.idle:
            self._handle_idle(timestamp)
        else:
            self._handle_active(timestamp, rule_match)

    def _handle_active(self, timestamp: datetime, rule_match: Optional[RuleMatch]):
        """Handle non-idle activity."""
        self.idle_start_time = None  # Reset idle tracking

        if rule_match:
            if self.current_session is None:
                # Start new session
                self._start_session(rule_match, timestamp)
            elif self.current_session.project_id != rule_match.project.id:
                # Different project matched - end current, start new
                self._end_session(timestamp)
                self._start_session(rule_match, timestamp)
            else:
                # Same project - extend session
                self.current_session.end_time = timestamp

            self.last_active_time = timestamp
        else:
            # No project matched - check grace period
            if self.current_session and self.last_active_time:
                gap = (timestamp - self.last_active_time).total_seconds()
                if gap >= self.config.session_grace_period:  # >= not >
                    # Grace period exceeded - end session at last active time
                    self._end_session(self.last_active_time)

    def _handle_idle(self, timestamp: datetime):
        """Handle idle activity."""
        if self.idle_start_time is None:
            self.idle_start_time = timestamp

        if self.current_session and self.last_active_time:
            idle_duration = (timestamp - self.idle_start_time).total_seconds()

            if idle_duration >= self.config.idle_grace_period:  # >= not >
                # Idle grace exceeded - end session at last active time
                # (do NOT count the idle grace time)
                self._end_session(self.last_active_time)

    def _start_session(self, rule_match: RuleMatch, timestamp: datetime):
        """Start a new tracking session."""
        self.current_session = Session(
            project_id=rule_match.project.id,
            start_time=timestamp,
            end_time=timestamp,
            triggered_by=rule_match.rule_description  # Actual rule info
        )
        self.last_active_time = timestamp

    def _end_session(self, end_time: datetime):
        """End the current session and save if meets minimum duration."""
        if self.current_session:
            self.current_session.end_time = end_time
            duration = (end_time - self.current_session.start_time).total_seconds()
            self.current_session.duration = int(duration)

            if duration >= self.config.min_session_duration:
                self._save_session(self.current_session)

            self.current_session = None
            self.idle_start_time = None

    def _save_session(self, session: Session):
        """Save session to database."""
        with get_db_connection(self.db_path) as conn:
            conn.execute("""
                INSERT INTO sessions
                (project_id, start_time, end_time, duration, triggered_by)
                VALUES (?, ?, ?, ?, ?)
            """, (
                session.project_id,
                format_utc_timestamp(session.start_time),
                format_utc_timestamp(session.end_time),
                session.duration,
                session.triggered_by
            ))

    def shutdown(self, timestamp: datetime):
        """
        Graceful shutdown - end any active session.
        Respects idle grace: if idle beyond grace period, ends at last_active_time.
        """
        if self.current_session:
            # If we've been idle beyond the grace period, end at last active time
            if self.idle_start_time and self.last_active_time:
                idle_duration = (timestamp - self.idle_start_time).total_seconds()
                if idle_duration >= self.config.idle_grace_period:
                    # Idle grace exceeded - don't count idle time
                    self._end_session(self.last_active_time)
                    return
            # Otherwise end at current timestamp
            self._end_session(timestamp)
```

### Activity Monitoring (macOS)

```python
from datetime import datetime, timezone
from typing import Optional
from dataclasses import dataclass
import time

# macOS APIs via PyObjC
from AppKit import NSWorkspace
from Quartz import CGEventSourceSecondsSinceLastEventType, kCGEventSourceStateHIDSystemState

@dataclass
class Activity:
    timestamp: datetime      # UTC
    app_name: Optional[str]
    bundle_id: Optional[str]
    window_title: Optional[str]
    file_path: Optional[str]
    url: Optional[str]
    idle: bool

def get_idle_seconds() -> float:
    """Get seconds since last keyboard/mouse input using monotonic time."""
    # This uses HID system state which is reliable
    return CGEventSourceSecondsSinceLastEventType(
        kCGEventSourceStateHIDSystemState,
        0xFFFFFFFF  # All event types
    )

def get_current_activity(idle_threshold: int) -> Activity:
    """Capture current user activity."""
    workspace = NSWorkspace.sharedWorkspace()
    active_app = workspace.frontmostApplication()

    app_name = None
    bundle_id = None

    if active_app:
        app_name = active_app.localizedName()
        bundle_id = active_app.bundleIdentifier()

    # Get window title from accessibility API
    window_title = get_focused_window_title()  # Requires Accessibility permission

    # Extract file path from window title (app-specific parsing)
    file_path = extract_file_path(app_name, window_title)

    # Extract URL if browser
    url = None
    if bundle_id and is_browser(bundle_id):
        url = get_browser_url(bundle_id)  # Requires Automation permission

    # Check if idle
    idle = get_idle_seconds() >= idle_threshold

    return Activity(
        timestamp=datetime.now(timezone.utc),
        app_name=app_name,
        bundle_id=bundle_id,
        window_title=window_title,
        file_path=file_path,
        url=url,
        idle=idle
    )

def get_focused_window_title() -> Optional[str]:
    """
    Get the title of the focused window.
    Requires Accessibility permission.
    """
    from ApplicationServices import (
        AXUIElementCreateSystemWide,
        AXUIElementCopyAttributeValue,
        kAXFocusedApplicationAttribute,
        kAXFocusedWindowAttribute,
        kAXTitleAttribute
    )

    try:
        system = AXUIElementCreateSystemWide()

        # Get focused application
        err, focused_app = AXUIElementCopyAttributeValue(
            system, kAXFocusedApplicationAttribute, None
        )
        if err != 0 or focused_app is None:
            return None

        # Get focused window
        err, focused_window = AXUIElementCopyAttributeValue(
            focused_app, kAXFocusedWindowAttribute, None
        )
        if err != 0 or focused_window is None:
            return None

        # Get window title
        err, title = AXUIElementCopyAttributeValue(
            focused_window, kAXTitleAttribute, None
        )
        if err != 0:
            return None

        return str(title) if title else None
    except Exception:
        return None

def is_browser(bundle_id: str) -> bool:
    """Check if bundle ID is a known browser."""
    browsers = {
        'com.apple.Safari',
        'com.google.Chrome',
        'com.google.Chrome.canary',
        'org.mozilla.firefox',
        'org.mozilla.firefoxdeveloperedition',
        'company.thebrowser.Browser',  # Arc
        'com.brave.Browser',
        'com.microsoft.edgemac',
        'com.vivaldi.Vivaldi',
        'com.operasoftware.Opera',
    }
    return bundle_id in browsers

def get_browser_url(bundle_id: str) -> Optional[str]:
    """
    Get current URL from browser via AppleScript/ScriptingBridge.
    Requires Automation permission (and possibly Screen Recording for some browsers).
    """
    import subprocess

    scripts = {
        'com.apple.Safari': '''
            tell application "Safari"
                if (count of windows) > 0 then
                    return URL of current tab of front window
                end if
            end tell
        ''',
        'com.google.Chrome': '''
            tell application "Google Chrome"
                if (count of windows) > 0 then
                    return URL of active tab of front window
                end if
            end tell
        ''',
        # Add more browsers as needed
    }

    script = scripts.get(bundle_id)
    if not script:
        return None

    try:
        result = subprocess.run(
            ['osascript', '-e', script],
            capture_output=True,
            text=True,
            timeout=1
        )
        if result.returncode == 0 and result.stdout.strip():
            return result.stdout.strip()
    except Exception:
        pass

    return None

def extract_file_path(app_name: Optional[str], window_title: Optional[str]) -> Optional[str]:
    """
    Extract file path from window title for known apps.
    """
    if not window_title:
        return None

    # VS Code / Cursor: "filename.py - project-name - Visual Studio Code"
    # or "filename.py - /path/to/project - Visual Studio Code"
    if app_name and ('Code' in app_name or 'Cursor' in app_name):
        parts = window_title.split(' - ')
        if len(parts) >= 2:
            # Check if second part looks like a path
            potential_path = parts[1].strip()
            if potential_path.startswith('/'):
                return f"{potential_path}/{parts[0].strip()}"

    # Add more app-specific parsing as needed
    return None
```

---

## Technical Architecture

### Directory Structure

```
~/.tt/
├── tt.db              # SQLite database
├── tt.pid             # Daemon PID file
├── tt.log             # Daemon log file
├── tt.lock            # Single-instance lock file
├── tt.sock            # Unix socket for IPC (pause/resume commands)
└── backups/
    └── tt_2026-01-13.db
```

**Important**: Ensure `~/.tt/` exists before opening log/db/pid files.

### Component Architecture

```
┌─────────────────────────────────────────────────────────────┐
│                        CLI (tt)                              │
│  - Argument parsing (Click)                                  │
│  - Output formatting (Rich)                                  │
│  - Database queries                                          │
└─────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────┐
│                    Daemon Process                            │
│  ┌─────────────────┐  ┌─────────────┐  ┌─────────────┐      │
│  │    Activity     │  │    Rule     │  │   Session   │      │
│  │    Monitor      │→ │   Engine    │→ │   Manager   │      │
│  │  (polls every   │  │(deterministic│  │ (idle-safe, │      │
│  │   N seconds)    │  │   order)    │  │    UTC)     │      │
│  └─────────────────┘  └─────────────┘  └─────────────┘      │
│         │                                   │                │
│         ▼                                   ▼                │
│  ┌─────────────────────────────────────────────────┐        │
│  │              SQLite Database                     │        │
│  │  (WAL mode, foreign_keys=ON, busy_timeout)      │        │
│  └─────────────────────────────────────────────────┘        │
└─────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────┐
│              Menu Bar Item (Optional)                        │
│  - Reads state from daemon/db                               │
│  - Minimal UI via rumps                                     │
└─────────────────────────────────────────────────────────────┘
```

### Technology Stack

| Component | Recommended | Alternative |
|-----------|-------------|-------------|
| Language | Python 3.10+ | Swift, Rust |
| CLI Framework | Click + Rich | argparse + tabulate |
| Database | SQLite3 | - |
| macOS APIs | PyObjC | Swift AppKit |
| Daemon | LaunchAgent plist | python-daemon |
| Menu Bar | rumps | Swift/AppKit |

### Dependencies

```
# requirements.txt
click>=8.0
rich>=13.0
pyobjc-framework-Cocoa>=10.0
pyobjc-framework-Quartz>=10.0
pyobjc-framework-ApplicationServices>=10.0
rumps>=0.4.0  # Optional, for menu bar
```

### Database Connection

```python
import os
import sqlite3
from pathlib import Path
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timezone

DB_PATH = Path.home() / ".tt" / "tt.db"

def format_utc_timestamp(dt: datetime) -> str:
    """
    Format datetime as UTC ISO 8601 with Z suffix.
    Ensures consistent timestamp format across all storage.
    """
    # Ensure UTC
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    else:
        dt = dt.astimezone(timezone.utc)
    # Format with Z suffix (not +00:00)
    return dt.strftime('%Y-%m-%dT%H:%M:%SZ')

def parse_utc_timestamp(s: str) -> datetime:
    """Parse UTC ISO 8601 timestamp (with Z or +00:00)."""
    s = s.replace('Z', '+00:00')
    return datetime.fromisoformat(s)

@contextmanager
def get_db_connection(db_path: Path = DB_PATH):
    """
    Get a database connection with proper settings.
    Uses WAL mode and busy timeout for concurrent access.
    Ensures file permissions are set to 600 for DB, WAL, and SHM files.
    """
    # Check if this is a new database (will be created by connect)
    is_new_db = not db_path.exists()

    # Set restrictive umask before creating DB to ensure WAL/SHM files
    # (tt.db-wal, tt.db-shm) are also created with 600 permissions.
    # This is critical for privacy - WAL/SHM can contain sensitive data.
    old_umask = os.umask(0o077)  # Only owner can read/write new files
    try:
        conn = sqlite3.connect(
            str(db_path),
            timeout=5.0,  # busy timeout in seconds
            isolation_level=None  # autocommit mode
        )
    finally:
        os.umask(old_umask)  # Restore original umask

    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA journal_mode = WAL")
    conn.execute("PRAGMA busy_timeout = 5000")
    conn.row_factory = sqlite3.Row

    # Also explicitly chmod existing files (handles upgrades from old versions)
    if is_new_db:
        os.chmod(db_path, 0o600)
    # Ensure WAL/SHM files have correct permissions if they exist
    for suffix in ['-wal', '-shm']:
        wal_shm_path = Path(str(db_path) + suffix)
        if wal_shm_path.exists():
            current_mode = wal_shm_path.stat().st_mode & 0o777
            if current_mode != 0o600:
                os.chmod(wal_shm_path, 0o600)

    try:
        yield conn
    finally:
        conn.close()

def init_database(db_path: Path = DB_PATH):
    """
    Initialize database schema and seed default settings.
    Safe to call multiple times (uses IF NOT EXISTS).
    MUST be called before any other database operations.
    """
    with get_db_connection(db_path) as conn:
        # Create tables (must match Data Model section exactly)
        conn.executescript("""
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
                project_id INTEGER NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
                rule_type TEXT NOT NULL,
                rule_value TEXT NOT NULL,
                rule_group INTEGER DEFAULT 0,
                enabled INTEGER DEFAULT 1,
                created_at TEXT DEFAULT CURRENT_TIMESTAMP
            );

            CREATE TABLE IF NOT EXISTS sessions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                project_id INTEGER NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
                start_time TEXT NOT NULL,
                end_time TEXT NOT NULL,
                duration INTEGER NOT NULL,
                triggered_by TEXT,
                created_at TEXT DEFAULT CURRENT_TIMESTAMP
            );

            CREATE TABLE IF NOT EXISTS settings (
                key TEXT PRIMARY KEY,
                value TEXT
            );

            -- Create indexes for common queries
            CREATE INDEX IF NOT EXISTS idx_activities_timestamp ON activities(timestamp);
            CREATE INDEX IF NOT EXISTS idx_activities_bundle_id ON activities(bundle_id);
            CREATE INDEX IF NOT EXISTS idx_blocks_start ON activity_blocks(start_time);
            CREATE INDEX IF NOT EXISTS idx_sessions_start ON sessions(start_time);
            CREATE INDEX IF NOT EXISTS idx_sessions_project ON sessions(project_id);
            CREATE INDEX IF NOT EXISTS idx_rules_project ON rules(project_id);
        """)

        # Seed default settings (INSERT OR IGNORE = don't overwrite existing)
        default_settings = {
            'poll_interval': '2',
            'idle_threshold': '120',
            'idle_grace_period': '300',
            'session_grace_period': '120',
            'min_session_duration': '60',
            'retention_days': '90',
            'blocks_retention_days': '90',
            'sessions_retention_days': '0',
            'week_start': 'monday',
            'tracking_paused': '0',
            'tracking_paused_at': None,
        }
        for key, value in default_settings.items():
            conn.execute(
                "INSERT OR IGNORE INTO settings (key, value) VALUES (?, ?)",
                (key, value)
            )

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
    week_start: str = 'monday'

def load_config(db_path: Path = DB_PATH) -> Config:
    """
    Load configuration from settings table.
    Returns Config with defaults if settings table doesn't exist yet.
    """
    config = Config()
    try:
        with get_db_connection(db_path) as conn:
            rows = conn.execute("SELECT key, value FROM settings").fetchall()
            settings = {row['key']: row['value'] for row in rows}

            if 'poll_interval' in settings:
                config.poll_interval = int(settings['poll_interval'])
            if 'idle_threshold' in settings:
                config.idle_threshold = int(settings['idle_threshold'])
            if 'idle_grace_period' in settings:
                config.idle_grace_period = int(settings['idle_grace_period'])
            if 'session_grace_period' in settings:
                config.session_grace_period = int(settings['session_grace_period'])
            if 'min_session_duration' in settings:
                config.min_session_duration = int(settings['min_session_duration'])
            if 'retention_days' in settings:
                config.retention_days = int(settings['retention_days'])
            if 'blocks_retention_days' in settings:
                config.blocks_retention_days = int(settings['blocks_retention_days'])
            if 'sessions_retention_days' in settings:
                config.sessions_retention_days = int(settings['sessions_retention_days'])
            if 'week_start' in settings:
                config.week_start = settings['week_start']
    except sqlite3.OperationalError:
        # Table doesn't exist yet - return defaults
        pass
    return config
```

### Daemon Implementation

```python
#!/usr/bin/env python3
# tt_daemon.py

import os
import sys
import time
import signal
import socket
import select
import logging
import fcntl
from pathlib import Path
from datetime import datetime, timezone
from typing import Optional

TT_DIR = Path.home() / ".tt"
DB_PATH = TT_DIR / "tt.db"
PID_PATH = TT_DIR / "tt.pid"
LOG_PATH = TT_DIR / "tt.log"
LOCK_PATH = TT_DIR / "tt.lock"
SOCK_PATH = TT_DIR / "tt.sock"

class SingleInstanceLock:
    """Ensure only one daemon instance runs at a time."""
    def __init__(self, lock_path: Path):
        self.lock_path = lock_path
        self.lock_file = None

    def acquire(self) -> bool:
        """Acquire exclusive lock. Returns False if another instance is running."""
        try:
            self.lock_file = open(self.lock_path, 'w')
            fcntl.flock(self.lock_file.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
            return True
        except (IOError, OSError):
            if self.lock_file:
                self.lock_file.close()
            return False

    def release(self):
        """Release the lock."""
        if self.lock_file:
            fcntl.flock(self.lock_file.fileno(), fcntl.LOCK_UN)
            self.lock_file.close()
            self.lock_file = None

class TTDaemon:
    def __init__(self, foreground: bool = False):
        self.running = True
        self.foreground = foreground
        self.config = load_config()
        # Pass db_path, not a connection (SessionManager opens connections as needed)
        self.session_manager = SessionManager(self.config, DB_PATH)
        self.lock = SingleInstanceLock(LOCK_PATH)
        self.ipc_socket: Optional[socket.socket] = None
        self.setup_logging()

    def setup_logging(self):
        """Configure logging - to file always, to stdout if foreground."""
        log_format = '[%(asctime)s] %(message)s'
        date_format = '%Y-%m-%d %H:%M:%S'

        # Always log to file
        file_handler = logging.FileHandler(str(LOG_PATH))
        file_handler.setFormatter(logging.Formatter(log_format, date_format))

        handlers = [file_handler]

        # Also log to stdout in foreground mode
        if self.foreground:
            stdout_handler = logging.StreamHandler(sys.stdout)
            stdout_handler.setFormatter(logging.Formatter(log_format, date_format))
            handlers.append(stdout_handler)

        logging.basicConfig(
            level=logging.INFO,
            handlers=handlers
        )

    def setup_ipc_socket(self):
        """Set up Unix socket for IPC (pause/resume commands)."""
        # Remove stale socket file
        if SOCK_PATH.exists():
            SOCK_PATH.unlink()

        self.ipc_socket = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        self.ipc_socket.bind(str(SOCK_PATH))
        self.ipc_socket.listen(1)
        self.ipc_socket.setblocking(False)
        os.chmod(SOCK_PATH, 0o600)
        logging.info(f"IPC socket listening on {SOCK_PATH}")

    def handle_ipc(self):
        """Check for and handle IPC commands (non-blocking)."""
        if not self.ipc_socket:
            return

        try:
            # Check if there's a connection waiting (non-blocking)
            readable, _, _ = select.select([self.ipc_socket], [], [], 0)
            if not readable:
                return

            conn, _ = self.ipc_socket.accept()
            try:
                data = conn.recv(1024).decode().strip()
                response = self.process_ipc_command(data)
                conn.sendall((response + "\n").encode())
            finally:
                conn.close()
        except Exception as e:
            logging.warning(f"IPC error: {e}")

    def process_ipc_command(self, command: str) -> str:
        """Process an IPC command and return response."""
        if command == "PAUSE":
            # End session immediately at last_active_time
            if self.session_manager.current_session:
                end_time = self.session_manager.last_active_time or datetime.now(timezone.utc)
                self.session_manager._end_session(end_time)
                logging.info("Session ended via PAUSE command")
            return "OK"
        elif command == "RESUME":
            logging.info("Tracking resumed via RESUME command")
            return "OK"
        elif command == "STATUS":
            if self.session_manager.current_session:
                return f"TRACKING:{self.session_manager.current_session.project_id}"
            return "IDLE"
        else:
            return "ERROR:Unknown command"

    def run(self):
        """Main daemon loop."""
        # Acquire single-instance lock
        if not self.lock.acquire():
            print("Another daemon instance is already running", file=sys.stderr)
            sys.exit(1)

        signal.signal(signal.SIGTERM, self.handle_signal)
        signal.signal(signal.SIGINT, self.handle_signal)

        # Set up IPC socket for pause/resume commands
        self.setup_ipc_socket()

        # Write PID file with proper permissions
        PID_PATH.write_text(str(os.getpid()))
        os.chmod(PID_PATH, 0o600)

        logging.info("Started monitoring")

        try:
            while self.running:
                try:
                    # Check for IPC commands (pause/resume)
                    self.handle_ipc()

                    activity = get_current_activity(self.config.idle_threshold)
                    self.save_activity(activity)
                    self.session_manager.process_activity(activity)
                    time.sleep(self.config.poll_interval)
                except Exception as e:
                    logging.error(f"Error in main loop: {e}")
        finally:
            self.shutdown()

    def save_activity(self, activity: Activity):
        """Save activity to database."""
        with get_db_connection(DB_PATH) as conn:
            conn.execute("""
                INSERT INTO activities
                (timestamp, app_name, bundle_id, window_title, file_path, url, idle)
                VALUES (?, ?, ?, ?, ?, ?, ?)
            """, (
                format_utc_timestamp(activity.timestamp),
                activity.app_name,
                activity.bundle_id,
                activity.window_title,
                activity.file_path,
                activity.url,
                1 if activity.idle else 0
            ))

    def handle_signal(self, signum, frame):
        """Handle shutdown signals gracefully."""
        logging.info(f"Received signal {signum}, shutting down")
        self.running = False

    def shutdown(self):
        """Graceful shutdown - end any active session."""
        if self.session_manager.current_session:
            now = datetime.now(timezone.utc)
            self.session_manager.shutdown(now)

        # Clean up IPC socket
        if self.ipc_socket:
            self.ipc_socket.close()
            if SOCK_PATH.exists():
                SOCK_PATH.unlink()

        # Release lock and remove PID file
        self.lock.release()
        if PID_PATH.exists():
            PID_PATH.unlink()

        logging.info("Daemon stopped")

def ensure_tt_dir():
    """Ensure ~/.tt/ directory exists with correct permissions."""
    TT_DIR.mkdir(mode=0o700, exist_ok=True)

def ensure_db_permissions(db_path: Path):
    """
    Ensure database file has correct permissions (600).
    Call this AFTER the database file is created.
    """
    if db_path.exists():
        current_mode = db_path.stat().st_mode & 0o777
        if current_mode != 0o600:
            os.chmod(db_path, 0o600)

def main(foreground: bool = False):
    ensure_tt_dir()
    # Initialize database schema and seed defaults (safe to call multiple times)
    init_database(DB_PATH)
    # Fix permissions on existing DBs that may have wrong perms (e.g., from old versions).
    # For new DBs, get_db_connection() sets 600 permissions immediately after creation.
    ensure_db_permissions(DB_PATH)
    daemon = TTDaemon(foreground=foreground)
    daemon.run()

if __name__ == "__main__":
    # CLI would parse --foreground flag and pass it here
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument('--foreground', action='store_true')
    args = parser.parse_args()
    main(foreground=args.foreground)
```

### LaunchAgent plist

Install at `~/Library/LaunchAgents/com.tt.daemon.plist`:

**Note**: The `tt daemon install` command should generate this plist dynamically with the correct paths for the user's system. The template below uses placeholders that must be expanded.

```xml
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>Label</key>
    <string>com.tt.daemon</string>
    <key>ProgramArguments</key>
    <array>
        <!-- Use full path to tt binary, discovered at install time -->
        <!-- e.g., /Users/jason/.local/bin/tt or result of `which tt` -->
        <string>{{TT_BINARY_PATH}}</string>
        <string>daemon</string>
        <string>start</string>
        <string>--foreground</string>
    </array>
    <key>RunAtLoad</key>
    <true/>
    <key>KeepAlive</key>
    <true/>
    <!-- launchd does NOT expand ~, must use full path -->
    <key>StandardOutPath</key>
    <string>{{HOME}}/.tt/tt.log</string>
    <key>StandardErrorPath</key>
    <string>{{HOME}}/.tt/tt.log</string>
    <key>WorkingDirectory</key>
    <string>{{HOME}}</string>
    <key>EnvironmentVariables</key>
    <dict>
        <key>PATH</key>
        <string>/usr/local/bin:/usr/bin:/bin:{{HOME}}/.local/bin</string>
        <key>HOME</key>
        <string>{{HOME}}</string>
    </dict>
</dict>
</plist>
```

**Example generated plist** (for user `jason`):

```xml
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>Label</key>
    <string>com.tt.daemon</string>
    <key>ProgramArguments</key>
    <array>
        <string>/Users/jason/.local/bin/tt</string>
        <string>daemon</string>
        <string>start</string>
        <string>--foreground</string>
    </array>
    <key>RunAtLoad</key>
    <true/>
    <key>KeepAlive</key>
    <true/>
    <key>StandardOutPath</key>
    <string>/Users/jason/.tt/tt.log</string>
    <key>StandardErrorPath</key>
    <string>/Users/jason/.tt/tt.log</string>
    <key>WorkingDirectory</key>
    <string>/Users/jason</string>
    <key>EnvironmentVariables</key>
    <dict>
        <key>PATH</key>
        <string>/usr/local/bin:/usr/bin:/bin:/Users/jason/.local/bin</string>
        <key>HOME</key>
        <string>/Users/jason</string>
    </dict>
</dict>
</plist>
```

The `--foreground` flag keeps the daemon in the foreground so launchd can manage it properly (restart on crash, etc.).

---

## Activity Monitoring (macOS Permissions)

### Required Permissions

| Permission | Purpose | Prompt Trigger |
|------------|---------|----------------|
| **Accessibility** | Read window titles | First AX API call |
| **Automation** | Get browser URLs via AppleScript | First osascript call |
| **Screen Recording** | Some browsers require this for URL access | May appear for certain browsers |

### Permission Failure Behavior

When permissions are denied or revoked, the daemon continues running with degraded functionality:

| Permission Denied | Behavior | Data Captured |
|-------------------|----------|---------------|
| **Accessibility** | Window title returns `None` | App name, bundle ID only |
| **Automation** | Browser URL returns `None` | App, window title, no URL |
| **Screen Recording** | Some browser URLs return `None` | Depends on browser |

**Fallback Rules**:
- The daemon should **never crash** due to permission errors.
- Missing data is stored as `NULL` in the database.
- Rules depending on missing fields (e.g., `url_contains` without URL permission) will not match.
- Daemon logs a warning on startup if permissions appear missing.
- CLI `tt daemon status` should indicate permission status.

**Permission Check on Startup**:
```
$ tt daemon status
Daemon Status: Running
PID: 12345
Permissions:
  Accessibility: ✓ Granted
  Automation:    ✗ Not granted (browser URLs unavailable)
  Screen Recording: ? Unknown (depends on browser)
```

### Notes

- Must run as a **LaunchAgent** (not LaunchDaemon) in the user session to access UI state
- Permissions are granted to the specific binary/app, not the user
- If running from Python, the Python interpreter needs permissions
- Consider wrapping in a minimal .app bundle for cleaner permission prompts

---

## Non-Functional Requirements

### Performance

| Metric | Target |
|--------|--------|
| Daemon CPU usage | < 1% average |
| Daemon memory | < 50MB |
| Activity capture latency | < 100ms |
| CLI response time | < 200ms |

### Database Growth

- Raw samples at 2s interval: ~15,000-40,000 rows/day depending on usage
- Expect **tens to hundreds of MB** per month
- Use retention policies to bound size:
  - `retention_days` for activities
  - `blocks_retention_days` for aggregated blocks
  - `sessions_retention_days` for sessions (0 = keep forever)

### Privacy & Security

- All data stored locally in `~/.tt/`
- No network requests
- No telemetry
- Database file permissions: 600 (owner read/write only)
  - Applies to `tt.db`, `tt.db-wal`, and `tt.db-shm` (WAL mode creates these auxiliary files)
  - Use restrictive umask (077) when creating DB to ensure WAL/SHM inherit correct permissions

### Reliability

- WAL mode + busy timeout to avoid "database is locked"
- Database transactions for data integrity
- Graceful shutdown preserves active session
- Automatic database backups (weekly)

### Compatibility

- macOS 11+ (Big Sur and later)
- Python 3.10+
- Accessibility permission required
- Automation permission required for browser URLs
- Screen Recording permission may be needed for some browsers

---

## Implementation Priority

### Phase 1: Core (MVP)
1. SQLite database setup (WAL, foreign_keys, schema)
2. Activity monitoring (app + window title)
3. Rule storage and evaluation (deterministic, null-safe)
4. Session tracking (UTC, idle grace)
5. Basic CLI: `status`, `projects`, `rules add/remove`, `today`

### Phase 2: Enhanced Tracking
6. Browser URL extraction (Safari, Chrome)
7. File path detection for IDEs
8. Idle detection with grace period
9. CLI: `stats`, `activity`, `rules test`

### Phase 3: Polish
10. Daemon management (`daemon start/stop/install`)
11. CLI: `export`, `config`, `db` commands
12. Activity aggregation and pruning
13. Rich formatted output

### Phase 4: Optional
14. Menu bar item
15. Additional browser support
16. Database backup automation

---

## Example Usage Workflow

```bash
# First time setup
$ tt daemon start
✓ Daemon started (PID: 12345)

# Create a project
$ tt projects add "Wonderstruck"
✓ Created project: Wonderstruck (ID: 1)

# Add rules for the project
$ tt rules add 1 path_prefix "/Users/jason/code/wonderstruck/"
✓ Added rule to Wonderstruck

$ tt rules add 1 url_contains "github.com/wonderstruck"
✓ Added rule to Wonderstruck

$ tt rules add 1 url_contains "figma.com/file/ws-design"
✓ Added rule to Wonderstruck

# Create AND rule group (must be in Figma AND window contains "Client A")
$ tt rules add 2 app "Figma" --group 1
$ tt rules add 2 window_contains "Client A" --group 1
✓ Added rules to Client A Redesign (AND group 1)

# Verify rules work
$ tt rules test
Current activity matches:
  → Wonderstruck (rule 1: path_prefix)

# Check status throughout the day
$ tt status
$ tt today

# End of week review
$ tt stats --period week

# Export for records
$ tt export --format csv --from 2026-01-01 --to 2026-01-31 --output january-2026.csv

# Install to run on login
$ tt daemon install
✓ Installed LaunchAgent
```

---

*End of PRD v4.8*
