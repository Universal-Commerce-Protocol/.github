#!/usr/bin/env python3
# /// script
# dependencies = [
#   "PyGithub",
#   "PyYAML",
# ]
# ///

#   Copyright 2026 UCP Authors
#
#   Licensed under the Apache License, Version 2.0 (the "License");
#   you may not use this file except in compliance with the License.
#   You may obtain a copy of the License at
#
#       http://www.apache.org/licenses/LICENSE-2.0
#
#   Unless required by applicable law or agreed to in writing, software
#   distributed under the License is distributed on an "AS IS" BASIS,
#   WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
#   See the License for the specific language governing permissions and
#   limitations under the License.

import sys
import unittest
from unittest.mock import MagicMock, patch
import os

# Mock the entire 'github' module before importing our script
mock_github = MagicMock()


class MockGithubException(Exception):
    def __init__(self, status, message, headers=None):
        super().__init__(message)
        self.status = status
        self.message = message


mock_github.GithubException = MockGithubException
sys.modules["github"] = mock_github
sys.modules["github.GithubException"] = MockGithubException

# Ensure current directory is search path to import target
sys.path.append(os.path.dirname(__file__))
import sync_labels  # noqa: E402


class CheckedTextTestResult(unittest.TextTestResult):
    """A custom TestResult class that prints green checkmarks for passing tests."""

    def addSuccess(self, test):
        super().addSuccess(test)
        # Print description/name of the test with green checkmark
        desc = test.shortDescription() or str(test)
        self.stream.writeln(f"  \033[92m✓\033[0m {desc}")
        self.stream.flush()

    def addFailure(self, test, err):
        super().addFailure(test, err)
        desc = test.shortDescription() or str(test)
        self.stream.writeln(f"  \033[91m✗ (Failed)\033[0m {desc}")
        self.stream.flush()

    def addError(self, test, err):
        super().addError(test, err)
        desc = test.shortDescription() or str(test)
        self.stream.writeln(f"  \033[93m⚠ (Error)\033[0m {desc}")
        self.stream.flush()


class CheckedTextTestRunner(unittest.TextTestRunner):
    """A test runner that uses CheckedTextTestResult."""

    def _makeResult(self):
        return CheckedTextTestResult(self.stream, self.descriptions, self.verbosity)


class TestLabelSync(unittest.TestCase):
    def setUp(self):
        mock_github.Github.reset_mock()

    def test_merge_labels_resolves_duplicates_correctly(self):
        """Merge raises ValueError on any duplicate labels"""
        list_a = [
            {
                "name": "bug",
                "color": "111111",
                "description": "Desc A",
                "aliases": [],
                "file_path": "general.yml",
            },
        ]
        list_b = [
            {
                "name": "bug",
                "color": "111111",
                "description": "Desc A",
                "aliases": [],
                "file_path": "triage.yml",
            },
        ]
        with self.assertRaises(ValueError) as ctx:
            sync_labels.merge_labels(list_a, list_b)
        self.assertIn("Duplicate label detected for 'bug'", str(ctx.exception))

    def test_merge_labels_throws_on_conflicting_duplicates(self):
        """Merge raises ValueError if duplicate label has conflicting color/description"""
        list_a = [
            {
                "name": "bug",
                "color": "111111",
                "description": "Desc A",
                "aliases": [],
                "file_path": "general.yml",
            },
        ]
        list_b = [
            {
                "name": "bug",
                "color": "222222",
                "description": "Conflicting Desc",
                "aliases": [],
                "file_path": "triage.yml",
            },
        ]
        with self.assertRaises(ValueError) as ctx:
            sync_labels.merge_labels(list_a, list_b)
        self.assertIn("Duplicate label detected for 'bug'", str(ctx.exception))
        self.assertIn("Defined in 'general.yml'", str(ctx.exception))
        self.assertIn("Defined in 'triage.yml'", str(ctx.exception))

    def test_merge_labels_throws_on_alias_conflicts(self):
        """Merge raises ValueError if an alias conflicts with a label name or another alias"""
        # Alias conflicts with label name
        list_a = [
            {
                "name": "bug",
                "color": "111111",
                "description": "Desc A",
                "aliases": ["issue"],
                "file_path": "general.yml",
            },
        ]
        list_b = [
            {
                "name": "issue",
                "color": "222222",
                "description": "Desc B",
                "aliases": [],
                "file_path": "triage.yml",
            },
        ]
        with self.assertRaises(ValueError) as ctx:
            sync_labels.merge_labels(list_a, list_b)
        self.assertIn("Conflict", str(ctx.exception))
        self.assertIn("general.yml", str(ctx.exception))
        self.assertIn("triage.yml", str(ctx.exception))

        # Duplicate aliases across different labels
        list_c = [
            {
                "name": "bug",
                "color": "111111",
                "description": "Desc A",
                "aliases": ["problem"],
                "file_path": "general.yml",
            },
            {
                "name": "defect",
                "color": "222222",
                "description": "Desc B",
                "aliases": ["problem"],
                "file_path": "triage.yml",
            },
        ]
        with self.assertRaises(ValueError) as ctx:
            sync_labels.validate_and_check_conflicts(list_c)
        self.assertIn(
            "Conflict: Alias 'problem' is defined for both label 'defect'",
            str(ctx.exception),
        )
        self.assertIn("general.yml", str(ctx.exception))
        self.assertIn("triage.yml", str(ctx.exception))

    def test_parse_yaml_labels_with_aliases(self):
        """Parse yaml configurations supporting inline and block aliases list"""
        yaml_content = """
- name: bug
  color: 'd73a4a'
  description: "Something isn't working"
  aliases:
    - error
    - issue
- name: enhancement
  color: a2eeef
  description: New feature or request
  aliases: feature, request
"""
        with patch("builtins.open", unittest.mock.mock_open(read_data=yaml_content)):
            labels = sync_labels.parse_yaml_labels("dummy.yml")
            sync_labels.validate_and_check_conflicts(labels, check_file_context=True)

        self.assertEqual(len(labels), 2)
        self.assertEqual(labels[0]["name"], "bug")
        self.assertEqual(labels[0]["aliases"], ["error", "issue"])
        self.assertEqual(labels[1]["name"], "enhancement")
        self.assertEqual(labels[1]["aliases"], ["feature", "request"])

    def test_verify_access_success(self):
        """Verify access succeeds when org and repos are readable"""
        g_mock = MagicMock()
        mock_github.Github.return_value = g_mock

        org_mock = MagicMock()
        g_mock.get_organization.return_value = org_mock

        repo_mock = MagicMock()
        repo_mock.name = "test-repo"
        org_mock.get_repo.return_value = repo_mock

        target_repos = sync_labels.verify_access(
            org_name="test-org",
            repo_names=["test-repo"],
            token="test-token",
        )
        self.assertEqual(len(target_repos), 1)
        self.assertEqual(target_repos[0].name, "test-repo")

    def test_alias_loop_detection(self):
        """Verify that simple self-loops or cyclic alias dependencies raise a ValueError"""
        # Self loop
        labels_self_loop = [
            {
                "name": "bug",
                "color": "111111",
                "description": "Desc",
                "aliases": ["bug"],
                "file_path": "general.yml",
            }
        ]
        with self.assertRaises(ValueError) as ctx:
            sync_labels.validate_and_check_conflicts(labels_self_loop)
        self.assertIn("cannot have itself as an alias", str(ctx.exception))

        # Multi-label cycle (A has alias B, B has alias A) -> represented as alias transitions B -> A and A -> B
        labels_cycle = [
            {
                "name": "bug",
                "color": "111111",
                "description": "Desc",
                "aliases": ["defect"],
                "file_path": "general.yml",
            },
            {
                "name": "defect",
                "color": "222222",
                "description": "Desc",
                "aliases": ["bug"],
                "file_path": "triage.yml",
            },
        ]
        with self.assertRaises(ValueError) as ctx:
            sync_labels.validate_and_check_conflicts(labels_cycle)
        self.assertIn("Cyclic alias dependency detected", str(ctx.exception))

    def test_schema_validations(self):
        """Verify that invalid hex colors or empty labels trigger schema errors once loaded"""
        # Blank name
        labels_empty_name = [
            {
                "name": "   ",
                "color": "111111",
                "description": "",
                "aliases": [],
                "file_path": "general.yml",
            }
        ]
        with self.assertRaises(ValueError) as ctx:
            sync_labels.validate_and_check_conflicts(labels_empty_name)
        self.assertIn("Label name cannot be empty or blank", str(ctx.exception))

        # Invalid hex code (e.g. too short or non-hex character)
        labels_invalid_color = [
            {
                "name": "bug",
                "color": "12345",
                "description": "Desc",
                "aliases": [],
                "file_path": "general.yml",
            }
        ]
        with self.assertRaises(ValueError) as ctx:
            sync_labels.validate_and_check_conflicts(labels_invalid_color)
        self.assertIn("invalid hex color", str(ctx.exception))

    def test_in_file_alias_name_overlap_throws(self):
        """Verify validate_and_check_conflicts catches an alias matching a defined label name in the same file"""
        labels = [
            {
                "name": "bug",
                "color": "111111",
                "description": "",
                "aliases": ["feature"],
                "file_path": "dummy.yml",
            },
            {
                "name": "feature",
                "color": "222222",
                "description": "",
                "aliases": [],
                "file_path": "dummy.yml",
            },
        ]
        with self.assertRaises(ValueError) as ctx:
            sync_labels.validate_and_check_conflicts(labels, check_file_context=True)
        self.assertIn(
            "is already defined as a separate label name in the same file",
            str(ctx.exception),
        )

    def test_live_configuration_files(self):
        """Verify that live general-labels.yml and triage-labels.yml are syntactically valid and conflict-free"""
        workspace_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
        general_path = os.path.join(
            workspace_dir,
            "org-tools",
            "labels",
            "general-labels.yml",
        )
        triage_path = os.path.join(
            workspace_dir, "org-tools", "labels", "triage-labels.yml"
        )

        # Confirm files exist
        self.assertTrue(
            os.path.exists(general_path),
            f"Missing configuration file at: {general_path}",
        )
        self.assertTrue(
            os.path.exists(triage_path),
            f"Missing configuration file at: {triage_path}",
        )

        # 1. Parse files
        general_labels = sync_labels.parse_yaml_labels(general_path)
        triage_labels = sync_labels.parse_yaml_labels(triage_path)

        # 2. Validate individual files
        try:
            sync_labels.validate_and_check_conflicts(
                general_labels, check_file_context=True
            )
        except ValueError as e:
            self.fail(f"Validation failed inside live 'general-labels.yml': {e}")

        try:
            sync_labels.validate_and_check_conflicts(
                triage_labels, check_file_context=True
            )
        except ValueError as e:
            self.fail(f"Validation failed inside live 'triage-labels.yml': {e}")

        # 3. Validate merged files
        try:
            _ = sync_labels.merge_labels(general_labels, triage_labels)
        except ValueError as e:
            self.fail(
                f"Conflict detected when merging live 'general-labels.yml' and 'triage-labels.yml':\n{e}"
            )

    def test_verify_access_failure_exits(self):
        """Verify access aborts execution when org or repo is inaccessible"""
        g_mock = MagicMock()
        mock_github.Github.return_value = g_mock

        g_mock.get_organization.side_effect = MockGithubException(404, "Not Found")

        with self.assertRaises(SystemExit):
            sync_labels.verify_access("fail-org", ["some-repo"], "token")

    def test_sync_labels_performs_renames_first(self):
        """Sync renames existing alias label to target label name instead of creating a duplicate"""
        repo_mock = MagicMock()
        repo_mock.name = "test-repo"

        label_old = MagicMock()
        label_old.name = "issue"
        label_old.color = "cccccc"
        label_old.description = "Old issue description"

        repo_mock.get_labels.return_value = [label_old]

        target_labels = [
            {
                "name": "bug",
                "color": "ff0000",
                "description": "New bug description",
                "aliases": ["issue"],
            }
        ]

        # Dry run mode
        sync_labels.sync_labels(
            org_name="test-org",
            target_repos=[repo_mock],
            target_labels=target_labels,
            dry_run=True,
        )
        label_old.edit.assert_not_called()

        # Apply mode
        sync_labels.sync_labels(
            org_name="test-org",
            target_repos=[repo_mock],
            target_labels=target_labels,
            dry_run=False,
        )
        label_old.edit.assert_called_once_with(
            name="bug", color="ff0000", description="New bug description"
        )


if __name__ == "__main__":
    unittest.main(testRunner=CheckedTextTestRunner(verbosity=2))
