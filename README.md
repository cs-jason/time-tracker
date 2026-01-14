# Time Tracker (tt)

CLI-first time tracking for macOS. Runs a background daemon that captures activity and automatically logs time to projects based on rules.

## Requirements

- macOS 11+ (Big Sur or later)
- Python 3.10+
- PyObjC (`pip3 install pyobjc`)
- Accessibility permission (for window titles)
- Automation permission (for browser URLs)
- Screen Recording permission (may be required for some browsers)

## Quick Start

```bash
# Run the CLI from the repo root
./tt projects add "My Project"
./tt rules add 1 app_contains "Code"

# Start daemon (foreground)
./tt daemon start --foreground
```

## Common Commands

```bash
./tt status
./tt today
./tt stats --period week

./tt projects list
./tt rules list

./tt tracking pause
./tt tracking resume

./tt daemon status
./tt daemon stop
```

## Permissions

- Accessibility: required to read window titles and document paths.
- Automation: required to run AppleScript for browser URLs.
- Screen Recording: some browsers require this to expose URLs.

If permissions are missing, the daemon keeps running with reduced data collection.

## Notes

- All timestamps are stored in UTC (ISO 8601 with `Z` suffix).
- Database lives at `~/.tt/tt.db` with restricted permissions (600).
- Raw activity samples are retained per `retention_days` setting.
