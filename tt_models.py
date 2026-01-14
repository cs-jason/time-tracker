#!/usr/bin/env python3
"""Shared data models."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Optional


@dataclass
class Activity:
    timestamp: datetime
    app_name: Optional[str]
    bundle_id: Optional[str]
    window_title: Optional[str]
    file_path: Optional[str]
    url: Optional[str]
    idle: bool
