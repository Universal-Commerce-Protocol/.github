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

"""Unit tests for the governance config parser."""

import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(
    0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../scripts"))
)


from governance_config_parser import (
    GovernanceConfig,
    GovernanceConfigParser,
    GovernanceRule,
    GovernanceConfigValidator,
    RuleRequirement,
    Team,
)


class TestGovernanceConfigParser(unittest.TestCase):
    """Tests for GovernanceConfigParser class."""

    def test_parse_valid_dict(self):
        """Test parsing a valid dictionary."""
        yaml_data = {
            "team_hierarchy": {
                "devops": 1,
                "maintainers": 2,
                "tech-council": 3,
            },
            "proxy_reviewers": ["proxy-user"],
            "fallback": {"requires": [{"min_team": "maintainers", "min_approvals": 1}]},
            "rules": [
                {
                    "name": "Core Rule",
                    "patterns": ["source/**/*.py"],
                    "excluded_patterns": ["source/special/**/*.py"],
                    "requires": [{"team": "tech-council", "min_approvals": 2}],
                }
            ],
        }

        parser = GovernanceConfigParser()
        config = parser._parse(yaml_data)

        # Assert Teams
        self.assertEqual(
            config.teams,
            {
                "devops": Team("devops", 1),
                "maintainers": Team("maintainers", 2),
                "tech-council": Team("tech-council", 3),
            },
        )

        # Assert Proxy Reviewers
        self.assertEqual(config.proxy_reviewers, {"proxy-user"})

        # Assert Fallback
        self.assertEqual(len(config.fallback), 1)
        self.assertEqual(config.fallback[0].min_approvals, 1)
        self.assertEqual(config.fallback[0].min_team, Team("maintainers", 2))
        self.assertIsNone(config.fallback[0].team)

        # Assert Rules
        self.assertEqual(len(config.rules), 1)
        rule = config.rules[0]
        self.assertEqual(rule.name, "Core Rule")
        self.assertEqual(rule.patterns, ["source/**/*.py"])
        self.assertEqual(rule.excluded_patterns, ["source/special/**/*.py"])
        self.assertEqual(len(rule.requires_all), 1)
        self.assertEqual(rule.requires_all[0].min_approvals, 2)
        self.assertEqual(rule.requires_all[0].team, Team("tech-council", 3))

    def test_parse_file_not_found(self):
        """Test parse_file raises FileNotFoundError for missing file."""
        parser = GovernanceConfigParser()
        with self.assertRaises(FileNotFoundError):
            parser.parse_file("non-existent-file.yml")

    def test_parse_invalid_yaml_syntax(self):
        """Test parse_file raises ValueError for invalid YAML."""
        parser = GovernanceConfigParser()
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir) / "invalid-config.yml"
            temp_path.write_text("invalid: yaml: : syntax", encoding="utf-8")

            with self.assertRaises(ValueError) as ctx:
                parser.parse_file(str(temp_path))
            self.assertIn("Failed to parse governance YAML", str(ctx.exception))

    def test_parse_invalid_root_type(self):
        """Test _parse raises ValueError when data is not a map."""
        parser = GovernanceConfigParser()
        with self.assertRaises(ValueError) as ctx:
            parser._parse(["not", "a", "map"])
        self.assertIn("must be a YAML map", str(ctx.exception))

    def test_min_approvals_validation(self):
        """Test validations for min_approvals values."""
        # 1. min_approvals missing/None
        with self.assertRaises(ValueError) as ctx:
            RuleRequirement(min_approvals=None, team=Team("devops", 1))
        self.assertIn("must be an integer", str(ctx.exception))

        # 2. min_approvals negative
        with self.assertRaises(ValueError) as ctx:
            RuleRequirement(min_approvals=-2, team=Team("devops", 1))
        self.assertIn("must be a positive integer", str(ctx.exception))

        # 3. min_approvals zero
        with self.assertRaises(ValueError) as ctx:
            RuleRequirement(min_approvals=0, team=Team("devops", 1))
        self.assertIn("must be a positive integer", str(ctx.exception))

    def test_rule_requirement_mutual_exclusion(self):
        """Test that team and min_team are mutually exclusive."""
        # Specifying both team and min_team
        with self.assertRaises(ValueError) as ctx:
            RuleRequirement(
                min_approvals=1, team=Team("devops", 1), min_team=Team("maintainers", 2)
            )
        self.assertIn("specify exactly one of", str(ctx.exception))

        # Specifying neither
        with self.assertRaises(ValueError) as ctx:
            RuleRequirement(min_approvals=1, team=None, min_team=None)
        self.assertIn("specify exactly one of", str(ctx.exception))

    def test_missing_team_in_hierarchy(self):
        """Test that referenced team must be defined in hierarchy."""
        yaml_data = {
            "team_hierarchy": {"devops": 1},
            "rules": [
                {
                    "name": "Rule with Typo",
                    "patterns": ["*"],
                    "requires": [{"team": "devops-typo", "min_approvals": 1}],
                }
            ],
        }
        parser = GovernanceConfigParser()
        with self.assertRaises(ValueError) as ctx:
            parser._parse(yaml_data)
        self.assertIn("not defined in team_hierarchy", str(ctx.exception))

    def test_fallback_type_validation(self):
        """Test that fallback requires block must be a list."""
        # Fallback requires is not a list
        yaml_data = {
            "team_hierarchy": {"devops": 1},
            "fallback": {"requires": "not-a-list"},
        }
        parser = GovernanceConfigParser()
        with self.assertRaises(ValueError) as ctx:
            parser._parse(yaml_data)
        self.assertIn("fallback requires must be a list", str(ctx.exception))

    def test_parse_mixed_case_normalization(self):
        """Test that team names in hierarchy, rules, and fallback are normalized to lowercase."""
        yaml_data = {
            "team_hierarchy": {
                "Tech-Council": 3,
                "MAINTAINERS": 2,
            },
            "proxy_reviewers": ["proxy-user"],
            "fallback": {"requires": [{"min_team": "MAINTAINERS", "min_approvals": 1}]},
            "rules": [
                {
                    "name": "Core Rule",
                    "patterns": ["source/**/*.py"],
                    "requires": [{"team": "Tech-Council", "min_approvals": 2}],
                }
            ],
        }

        parser = GovernanceConfigParser()
        config = parser._parse(yaml_data)

        # Verify teams dictionary keys and Team object names are lowercased
        self.assertEqual(
            config.teams,
            {
                "tech-council": Team("tech-council", 3),
                "maintainers": Team("maintainers", 2),
            },
        )

        # Verify fallback and rules resolved team references are lowercased
        self.assertEqual(config.fallback[0].min_team.name, "maintainers")
        self.assertEqual(config.rules[0].requires_all[0].team.name, "tech-council")


class TestGovernanceConfigValidator(unittest.TestCase):
    """Tests for GovernanceConfigValidator class."""

    def setUp(self):
        """Set up test fixtures."""
        self.hierarchy = {
            "devops": Team("devops", 1),
            "maintainers": Team("maintainers", 2),
        }

    @patch("governance_config_parser.GovernanceConfigValidator._get_tracked_files")
    def test_validate_overlaps_success(self, mock_get_files):
        """Test validate_overlaps returns no errors when rules do not overlap."""
        mock_get_files.return_value = [
            "src/main.py",
            "docs/index.md",
            "docs/specification/index.md",
        ]

        rule_source = GovernanceRule(
            name="Source", patterns=["src/**/*.py"], requires_all=[]
        )
        rule_docs_general = GovernanceRule(
            name="Docs General",
            patterns=["docs/**/*.md"],
            excluded_patterns=["docs/specification/**/*.md"],
            requires_all=[],
        )
        rule_docs_spec = GovernanceRule(
            name="Docs Spec", patterns=["docs/specification/**/*.md"], requires_all=[]
        )

        config = GovernanceConfig(
            teams=self.hierarchy,
            rules=[rule_source, rule_docs_general, rule_docs_spec],
            fallback=[],
            proxy_reviewers=set(),
        )

        validator = GovernanceConfigValidator(config)
        errors = validator.validate_overlaps(repo_path="/dummy")
        self.assertEqual(len(errors), 0)

    @patch("governance_config_parser.GovernanceConfigValidator._get_tracked_files")
    def test_validate_overlaps_failure(self, mock_get_files):
        """Test validate_overlaps returns errors when rules overlap."""
        mock_get_files.return_value = ["docs/specification/index.md"]

        rule_docs_general = GovernanceRule(
            name="Docs General", patterns=["docs/**/*.md"], requires_all=[]
        )
        rule_docs_spec = GovernanceRule(
            name="Docs Spec", patterns=["docs/specification/**/*.md"], requires_all=[]
        )

        config = GovernanceConfig(
            teams=self.hierarchy,
            rules=[rule_docs_general, rule_docs_spec],
            fallback=[],
            proxy_reviewers=set(),
        )

        validator = GovernanceConfigValidator(config)
        errors = validator.validate_overlaps(repo_path="/dummy")
        self.assertEqual(len(errors), 1)
        self.assertIn("matches multiple rules", errors[0].message)

    def test_rule_pattern_matching_edge_cases(self):
        """Tests the custom glob-to-regex engine in GovernanceRule."""
        rule = GovernanceRule(
            name="Regex Test",
            patterns=["src/**/*.py", "tests/*.py", "docs/file_?.md"],
            requires_all=[],
        )

        # Should Match
        self.assertTrue(rule.matches("src/main.py"))
        self.assertTrue(rule.matches("src/nested/deep/main.py"))
        self.assertTrue(rule.matches("tests/test_main.py"))
        self.assertTrue(rule.matches("docs/file_1.md"))
        self.assertTrue(rule.matches("docs/file_A.md"))

        # Should Not Match
        self.assertFalse(rule.matches("src_backup/main.py"))  # prefix mismatch
        self.assertFalse(
            rule.matches("tests/nested/test_main.py")
        )  # Single * shouldn't cross directories
        self.assertFalse(rule.matches("docs/file_10.md"))  # ? is only one character
        self.assertFalse(rule.matches("src/main.js"))  # wrong extension

    @patch("governance_config_parser.GovernanceConfigValidator._get_tracked_files")
    def test_validate_no_fallback_success(self, mock_get_files):
        """Test validate_no_fallback returns no errors when all files match a rule."""
        mock_get_files.return_value = [
            "src/main.py",
            "docs/index.md",
        ]

        rule_source = GovernanceRule(
            "Source", patterns=["src/**/*.py"], requires_all=[]
        )
        rule_docs = GovernanceRule("Docs", patterns=["docs/**/*.md"], requires_all=[])

        config = GovernanceConfig(
            teams=self.hierarchy,
            rules=[rule_source, rule_docs],
            fallback=[],
            proxy_reviewers=set(),
        )

        validator = GovernanceConfigValidator(config)
        errors = validator.validate_no_fallback(repo_path="/dummy")
        self.assertEqual(len(errors), 0)

    @patch("governance_config_parser.GovernanceConfigValidator._get_tracked_files")
    def test_validate_no_fallback_failure(self, mock_get_files):
        """Test validate_no_fallback returns errors for files not matching any rule."""
        mock_get_files.return_value = [
            "src/main.py",
            "unmatched_file.txt",
        ]

        rule_source = GovernanceRule(
            "Source", patterns=["src/**/*.py"], requires_all=[]
        )

        config = GovernanceConfig(
            teams=self.hierarchy,
            rules=[rule_source],
            fallback=[],
            proxy_reviewers=set(),
        )

        validator = GovernanceConfigValidator(config)
        errors = validator.validate_no_fallback(repo_path="/dummy")
        self.assertEqual(len(errors), 1)
        self.assertEqual(errors[0].file_path, "unmatched_file.txt")
        self.assertIn("does not match any governance rule", errors[0].message)


if __name__ == "__main__":
    unittest.main()
