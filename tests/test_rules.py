import unittest
from datetime import datetime, timezone

from tt_models import Activity
from tt_rules import Rule, rule_matches


class TestRuleMatching(unittest.TestCase):
    def setUp(self):
        self.base = Activity(
            timestamp=datetime.now(timezone.utc),
            app_name="Visual Studio Code",
            bundle_id="com.microsoft.VSCode",
            window_title="main.py - my-project",
            file_path="/Users/jason/code/my-project/main.py",
            url="https://github.com/jason/repo",
            idle=False,
        )

    def test_app_matches_name_or_bundle(self):
        rule = Rule(1, 1, "app", "visual studio code", 0, True)
        self.assertTrue(rule_matches(self.base, rule))
        rule2 = Rule(2, 1, "app", "com.microsoft.vscode", 0, True)
        self.assertTrue(rule_matches(self.base, rule2))

    def test_contains_case_insensitive(self):
        rule = Rule(3, 1, "window_contains", "MY-PROJECT", 0, True)
        self.assertTrue(rule_matches(self.base, rule))

    def test_path_prefix(self):
        rule = Rule(4, 1, "path_prefix", "/users/jason/code/", 0, True)
        self.assertTrue(rule_matches(self.base, rule))

    def test_regex_search(self):
        rule = Rule(5, 1, "window_regex", r".*\.py - .*", 0, True)
        self.assertTrue(rule_matches(self.base, rule))

    def test_missing_fields(self):
        activity = Activity(
            timestamp=datetime.now(timezone.utc),
            app_name=None,
            bundle_id=None,
            window_title=None,
            file_path=None,
            url=None,
            idle=False,
        )
        rule = Rule(6, 1, "window_contains", "foo", 0, True)
        self.assertFalse(rule_matches(activity, rule))


if __name__ == "__main__":
    unittest.main()
