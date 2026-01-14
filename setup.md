# Pre-Prod Test Checklist (tt)

Follow these steps in order before moving to production.

## 1) Verify prerequisites

1. Confirm macOS 11+.
2. Confirm Python 3.10+:
   ```bash
   python3 --version
   ```
3. Install PyObjC (required for AppKit/Quartz):
   ```bash
   pip3 install pyobjc
   ```

## 2) Install tt

Option A - Remote install:
```bash
curl -fsSL https://raw.githubusercontent.com/cs-jason/time-tracker/main/install-remote.sh | bash
```

Option B - Local install:
```bash
git clone https://github.com/cs-jason/time-tracker.git
cd time-tracker
chmod +x install.sh
./install.sh
```

## 3) Clean local state (optional but recommended)

1. Stop any running daemon:
   ```bash
   tt stop
   ```
2. Move any existing database aside (optional if you want a clean run):
   ```bash
   mv ~/.tt/tt.db ~/.tt/tt.db.backup.$(date +%Y%m%d%H%M%S)
   ```

## 4) Run unit tests

```bash
python3 -m unittest discover -s tests
```

## 5) Initialize DB + verify permissions

1. Trigger DB creation:
   ```bash
   tt projects list
   ```
2. Check permissions:
   ```bash
   ls -l ~/.tt/tt.db
   ```
   Expect `-rw-------` (600).

## 6) Create sample data

```bash
tt projects add "Test Project"
tt rules add 1 app_contains "Code"
```

## 7) Start daemon and grant permissions

1. Start daemon:
   ```bash
   tt start
   ```
2. When prompted, grant:
   - Accessibility
   - Automation (for browser URLs)
   - Screen Recording (if requested)

Leave it running for a few minutes while switching between apps.

## 8) Validate live capture

Open a second terminal and run:

```bash
tt status
tt activity --limit 10
tt rules test
```

Confirm:
- `status` shows current app and window title.
- `activity` shows recent samples with timestamps.
- `rules test` matches the expected project.

## 9) Validate session tracking

1. Work in an app that matches a rule for a few minutes.
2. Switch to a non-matching app briefly and return.
3. Check summary:
   ```bash
   tt today
   tt stats --period day
   ```

Confirm:
- Sessions are recorded.
- Short non-matching gaps do not create a new session.
- Idle time is not counted beyond grace.

## 10) Validate exports

```bash
tt export --format json --output /tmp/tt-sessions.json
tt export --format csv --output /tmp/tt-activities.csv --table activities
```

Confirm exported files exist and contain data.

## 11) Validate retention + backups

```bash
tt db prune
tt db backup
ls -l ~/.tt/backups
```

Confirm:
- Prune reports deleted rows (if any).
- Backup file is created in `~/.tt/backups`.

## 12) Install LaunchAgent (optional)

To start tt automatically on login:

```bash
tt start --install
```

This creates `~/Library/LaunchAgents/com.tt.daemon.plist`.

## 13) Stop daemon after testing

```bash
tt stop
```

---

If all steps pass, the build is ready for production rollout.
