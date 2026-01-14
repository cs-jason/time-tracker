#!/usr/bin/env python3
"""Output formatting helpers."""
from __future__ import annotations

from typing import Iterable, List

# Bar characters
BAR_FILLED = "█"
BAR_EMPTY = "░"

# Section separators
LINE_SINGLE = "────────────────────────────────────────────────────"
LINE_DOUBLE = "════════════════════════════════════════════════════"


def format_hours(seconds: float) -> str:
    """Format seconds as compact hours (e.g., '12.5h', '0.5h', '0h')."""
    hours = seconds / 3600
    if hours == 0:
        return "0h"
    if hours < 0.1:
        return f"{hours:.2f}h"
    if hours < 10:
        return f"{hours:.1f}h"
    return f"{hours:.0f}h"


def format_percentage(value: float, total: float) -> str:
    """Format as percentage (e.g., '38%')."""
    if total == 0:
        return "0%"
    pct = (value / total) * 100
    return f"{pct:.0f}%"


def progress_bar(value: float, max_value: float, width: int = 12) -> str:
    """Create a progress bar (e.g., '████████░░░░')."""
    if max_value == 0:
        return BAR_EMPTY * width
    ratio = min(value / max_value, 1.0)
    filled = int(ratio * width)
    empty = width - filled
    return BAR_FILLED * filled + BAR_EMPTY * empty


def print_table(headers: List[str], rows: Iterable[Iterable[str]]) -> None:
    rows = list(rows)
    widths = [len(h) for h in headers]
    for row in rows:
        for i, cell in enumerate(row):
            widths[i] = max(widths[i], len(cell))

    header_line = "  ".join(h.ljust(widths[i]) for i, h in enumerate(headers))
    sep_line = "  ".join("-" * widths[i] for i in range(len(headers)))
    print(header_line)
    print(sep_line)
    for row in rows:
        print("  ".join(cell.ljust(widths[i]) for i, cell in enumerate(row)))
