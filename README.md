# Time Tracker (tt)

CLI-first time tracking for macOS. Runs a background daemon that captures activity and automatically logs time to projects based on rules.

## Install

```bash
curl -fsSL https://raw.githubusercontent.com/cs-jason/time-tracker/main/install-remote.sh | bash
```

Or clone and install locally:

```bash
git clone https://github.com/cs-jason/time-tracker.git
cd time-tracker
./install.sh
```

## Requirements

- macOS 11+ (Big Sur or later)
- Python 3.10+
- PyObjC (`pip3 install pyobjc`)

## Quick Start

```bash
# Install and start tracking
tt start --install

# Add a project and rule
tt projects add "My Project"
tt rules add 1 app_contains "Code"

# Check status
tt status
tt today
```

## Commands

```
tt start        Start tracking (daemon + monitoring)
tt stop         Stop tracking
tt status       Show current activity and tracking status
tt today        Show today's tracked time
tt stats        Show statistics (day/week/month/year)
tt activity     Show raw activity samples
tt projects     Manage projects
tt rules        Manage auto-tracking rules
tt config       View or set configuration
tt export       Export data to CSV/JSON
tt db           Database maintenance (backup/prune)
```

## Example Usage

```bash
# View weekly stats with visual breakdown
tt stats --period week

# Add projects and rules
tt projects add "Client Work" --color "#3b82f6"
tt rules add 1 app_exact "Figma"
tt rules add 1 path_contains "/projects/client"

# Export data
tt export --format json --output ~/Desktop/time-data.json

# Database maintenance
tt db backup
tt db prune
```

## Permissions

When you first run `tt start`, macOS will prompt for:

- **Accessibility**: Required to read window titles and document paths
- **Automation**: Required for browser URL detection
- **Screen Recording**: Some browsers require this to expose URLs

If permissions are missing, the daemon keeps running with reduced data collection.

## Data Storage

- Database: `~/.tt/tt.db` (permissions: 600)
- Backups: `~/.tt/backups/`
- Logs: `~/.tt/tt.log`
- All timestamps stored in UTC (ISO 8601)

## Uninstall

```bash
tt stop
rm -rf ~/.tt
rm ~/.local/bin/tt
# Or if installed to /usr/local/bin:
sudo rm /usr/local/bin/tt
```
