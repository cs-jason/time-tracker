#!/usr/bin/env python3
"""Rule engine for matching activities to projects."""
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Dict, List, Optional, Tuple

from tt_db import DB_PATH, get_db_connection
from tt_models import Activity


@dataclass
class Rule:
    id: int
    project_id: int
    rule_type: str
    rule_value: str
    rule_group: int
    enabled: bool


@dataclass
class ProjectRules:
    id: int
    name: str
    rules: List[Rule]


@dataclass
class MatchResult:
    project_id: int
    triggered_by: str


RULE_TYPES = {
    "app",
    "app_contains",
    "window_contains",
    "window_regex",
    "path_prefix",
    "path_contains",
    "url_contains",
    "url_regex",
}


class RuleEngine:
    def __init__(self, db_path=DB_PATH):
        self.db_path = db_path
        self.projects: List[ProjectRules] = []
        self.reload()

    def reload(self) -> None:
        """Reload projects and rules from database."""
        with get_db_connection(self.db_path) as conn:
            projects = conn.execute(
                "SELECT id, name FROM projects WHERE archived = 0 ORDER BY id"
            ).fetchall()
            rules = conn.execute(
                "SELECT id, project_id, rule_type, rule_value, rule_group, enabled "
                "FROM rules WHERE enabled = 1 ORDER BY id"
            ).fetchall()

        rules_by_project: Dict[int, List[Rule]] = {}
        for row in rules:
            rule = Rule(
                id=row["id"],
                project_id=row["project_id"],
                rule_type=row["rule_type"],
                rule_value=row["rule_value"],
                rule_group=row["rule_group"],
                enabled=bool(row["enabled"]),
            )
            rules_by_project.setdefault(rule.project_id, []).append(rule)

        self.projects = [
            ProjectRules(id=proj["id"], name=proj["name"], rules=rules_by_project.get(proj["id"], []))
            for proj in projects
        ]

    def match(self, activity: Activity) -> Optional[MatchResult]:
        """Return the first matching project based on deterministic order."""
        for project in self.projects:
            ungrouped = [r for r in project.rules if r.rule_group == 0]
            grouped = [r for r in project.rules if r.rule_group != 0]

            # Ungrouped rules first, ascending rule_id
            for rule in sorted(ungrouped, key=lambda r: r.id):
                if rule_matches(activity, rule):
                    return MatchResult(
                        project_id=project.id,
                        triggered_by=f"{rule.rule_type}: {rule.rule_value}",
                    )

            # Grouped rules: ascending group, then rule_id
            if grouped:
                groups: Dict[int, List[Rule]] = {}
                for rule in grouped:
                    groups.setdefault(rule.rule_group, []).append(rule)
                for group_id in sorted(groups.keys()):
                    rules_in_group = sorted(groups[group_id], key=lambda r: r.id)
                    if all(rule_matches(activity, rule) for rule in rules_in_group):
                        parts = [f"{r.rule_type}:{r.rule_value}" for r in rules_in_group]
                        description = f"group {group_id}: " + " AND ".join(parts)
                        return MatchResult(project_id=project.id, triggered_by=description)

        return None


def _norm(value: Optional[str]) -> Optional[str]:
    return value.lower() if isinstance(value, str) else None


def rule_matches(activity: Activity, rule: Rule) -> bool:
    if rule.rule_type not in RULE_TYPES:
        return False

    value = rule.rule_value

    if rule.rule_type == "app":
        if activity.app_name is None and activity.bundle_id is None:
            return False
        return (
            _norm(activity.app_name) == value.lower()
            or _norm(activity.bundle_id) == value.lower()
        )

    if rule.rule_type == "app_contains":
        return _contains(activity.app_name, value)

    if rule.rule_type == "window_contains":
        return _contains(activity.window_title, value)

    if rule.rule_type == "window_regex":
        return _regex_search(activity.window_title, value)

    if rule.rule_type == "path_prefix":
        return _prefix(activity.file_path, value)

    if rule.rule_type == "path_contains":
        return _contains(activity.file_path, value)

    if rule.rule_type == "url_contains":
        return _contains(activity.url, value)

    if rule.rule_type == "url_regex":
        return _regex_search(activity.url, value)

    return False


def _contains(haystack: Optional[str], needle: str) -> bool:
    if haystack is None:
        return False
    return needle.lower() in haystack.lower()


def _prefix(haystack: Optional[str], needle: str) -> bool:
    if haystack is None:
        return False
    return haystack.lower().startswith(needle.lower())


def _regex_search(haystack: Optional[str], pattern: str) -> bool:
    if haystack is None:
        return False
    try:
        return re.search(pattern, haystack) is not None
    except re.error:
        return False
