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

import os
import re
import subprocess
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Set

from pr_models import Team, RuleRequirement, merge_requirements
import yaml


@dataclass(frozen=True)
class GovernanceRule:
    """Represents a specific rule with name, file patterns, requirements, and exclusions."""

    name: str
    patterns: List[str]
    requires_all: List[RuleRequirement]
    excluded_patterns: List[str] = field(default_factory=list)

    # Internal compiled pattern fields
    _compiled_patterns: List[re.Pattern] = field(init=False, repr=False)
    _compiled_excludes: List[re.Pattern] = field(init=False, repr=False)

    def __post_init__(self):
        # Pre-compile and cache regexes on instantiation
        object.__setattr__(
            self,
            "_compiled_patterns",
            [self._compile_pattern(p) for p in self.patterns],
        )
        object.__setattr__(
            self,
            "_compiled_excludes",
            [self._compile_pattern(p) for p in self.excluded_patterns],
        )

    def matches(self, file_path: str) -> bool:
        """Checks if a file path matches the rule (matches patterns and is not excluded)."""
        # Cross-platform normalization to POSIX forward-slash standard
        posix_path = Path(file_path).as_posix()
        for compiled_exclude in self._compiled_excludes:
            if compiled_exclude.match(posix_path):
                return False
        for compiled_pattern in self._compiled_patterns:
            if compiled_pattern.match(posix_path):
                return True
        return False

    @staticmethod
    def _compile_pattern(pattern: str) -> re.Pattern:
        """Translates a glob pattern into a compiled regex Pattern."""
        escaped = re.escape(pattern)
        # Translate wildcards to regex equivalents:
        # 1. '**/ ' matches zero or more directories
        regex_str = escaped.replace(r"\*\*/", "(?:.*/)?")
        # 2. Trailing '**' matches anything
        regex_str = regex_str.replace(r"\*\*", ".*")
        # 3. '*' matches any filename segment (excluding '/')
        regex_str = regex_str.replace(r"\*", "[^/]*")
        # 4. '?' matches a single character (excluding '/')
        regex_str = regex_str.replace(r"\?", "[^/]")
        return re.compile(rf"^{regex_str}$")


@dataclass
class GovernanceConfig:
    """Represents the complete governance configuration."""

    teams: Dict[str, Team]
    rules: List[GovernanceRule]
    fallback: List[RuleRequirement]
    proxy_reviewers: Set[str]

    def _get_requirements_for_file(self, file_path: str) -> List[RuleRequirement]:
        """Get the merged requirements that apply to a specific file."""
        matched_rules = []
        for rule in self.rules:
            if rule.matches(file_path):
                matched_rules.append(rule)

        if not matched_rules:
            return self.fallback

        # De-duplicate rules by name, preserving order
        unique_rules = list({r.name: r for r in matched_rules}.values())
        requirements = []
        for r in unique_rules:
            requirements.extend(r.requires_all)

        return merge_requirements(requirements)

    def get_applicable_requirements(
        self, changed_files: List[str]
    ) -> Dict[str, List[RuleRequirement]]:
        """Identify all rule requirements that apply to each of the PR's changed files."""
        return {file: self._get_requirements_for_file(file) for file in changed_files}


@dataclass
class ValidationError:
    """Represents a validation error in the governance rules configuration."""

    file_path: str
    message: str

    def __str__(self) -> str:
        return self.message


class GovernanceConfigParser:
    """Parser for reading, parsing, and validating governance rules configuration files."""

    def __init__(self, repo_root: Optional[str] = None):
        """Initializes the parser, optionally specifying a repository root."""
        self.repo_root = repo_root

    def parse_file(self, file_path: str) -> GovernanceConfig:
        """Reads, parses, and validates the governance YAML file, mapping to typed dataclasses."""
        file_path_obj = Path(file_path)
        if not file_path_obj.exists():
            raise FileNotFoundError(f"Governance file not found at '{file_path}'.")

        try:
            with open(file_path_obj, "r", encoding="utf-8") as f:
                data = yaml.safe_load(f)
        except Exception as e:
            raise ValueError(f"Failed to parse governance YAML: {e}")

        return self._parse(data)

    def _parse(self, data: Any) -> GovernanceConfig:
        """Parses a dictionary representing governance rules configuration into typed dataclasses."""
        if not isinstance(data, dict):
            raise ValueError("Governance configuration must be a YAML map.")

        teams = self._parse_team_hierarchy(data)
        fallback = self._parse_fallback(data, teams)
        rules = self._parse_rules(data, teams)
        proxy_reviewers = self._parse_proxy_reviewers(data)

        return GovernanceConfig(
            teams=teams,
            rules=rules,
            fallback=fallback,
            proxy_reviewers=proxy_reviewers,
        )

    def _parse_team_hierarchy(self, data: dict) -> Dict[str, Team]:
        """Parses the team group hierarchy ranks."""
        team_hierarchy_yaml = data.get("team_hierarchy", {})
        if not isinstance(team_hierarchy_yaml, dict):
            raise ValueError("team_hierarchy must be a map.")

        hierarchy = {}
        for team, level in team_hierarchy_yaml.items():
            if not isinstance(level, int):
                raise ValueError(
                    f"Hierarchy rank level for team '{team}' must be an integer."
                )
            hierarchy[team.lower()] = Team.create(name=team, level=level)
        return hierarchy

    def _parse_proxy_reviewers(self, data: dict) -> Set[str]:
        """Parses the set of proxy reviewers."""
        return {r.lower() for r in data.get("proxy_reviewers", [])}

    def _parse_fallback(
        self, data: dict, teams: Dict[str, Team]
    ) -> List[RuleRequirement]:
        """Parses the fallback rule requirements."""
        fallback_yaml = data.get("fallback", {})
        if not isinstance(fallback_yaml, dict):
            raise ValueError("fallback configuration must be a map.")
        requires = fallback_yaml.get("requires", [])
        if not isinstance(requires, list):
            raise ValueError("fallback requires must be a list.")
        return self._parse_requirements(requires, teams)

    def _parse_rules(self, data: dict, teams: Dict[str, Team]) -> List[GovernanceRule]:
        """Parses the list of governance rules."""
        rules_yaml = data.get("rules", [])
        if not isinstance(rules_yaml, list):
            raise ValueError("rules must be a list.")

        return [self._parse_rule(rule_data, teams) for rule_data in rules_yaml]

    def _parse_rule(self, rule_data: dict, teams: Dict[str, Team]) -> GovernanceRule:
        """Parses a single governance rule."""
        name = rule_data.get("name", "Unnamed Rule")
        patterns = rule_data.get("patterns", [])
        if isinstance(patterns, str):
            patterns = [patterns]

        # Support both 'excluded_patterns' and 'excludes' (for backward compatibility)
        excludes = rule_data.get("excluded_patterns", rule_data.get("excludes", []))
        if isinstance(excludes, str):
            excludes = [excludes]

        requires_all = self._parse_requirements(rule_data.get("requires", []), teams)
        return GovernanceRule(
            name=name,
            patterns=patterns,
            requires_all=requires_all,
            excluded_patterns=excludes,
        )

    def _resolve_team(
        self, team_name: str, teams: Dict[str, Team], is_min: bool = False
    ) -> Team:
        """Resolves a team name to a Team object, checking that it exists in the hierarchy."""
        team_name_lower = team_name.lower()
        if team_name_lower not in teams:
            prefix = "Min team" if is_min else "Team"
            raise ValueError(
                f"{prefix} '{team_name}' specified in requirements is not defined in team_hierarchy."
            )
        return teams[team_name_lower]

    def _parse_requirements(
        self, requires_yaml: List[Dict[str, Any]], teams: Dict[str, Team]
    ) -> List[RuleRequirement]:
        """Parses rule requirement constraints, resolving team string names to Team objects."""
        requirements = []
        for req in requires_yaml:
            min_approvals = req.get("min_approvals")
            if (
                min_approvals is None
                or not isinstance(min_approvals, int)
                or min_approvals <= 0
            ):
                raise ValueError(
                    "Requirement must include a positive integer 'min_approvals'."
                )

            team_str = req.get("team")
            min_team_str = req.get("min_team")

            team = (
                self._resolve_team(team_str, teams, is_min=False)
                if team_str is not None
                else None
            )
            min_team = (
                self._resolve_team(min_team_str, teams, is_min=True)
                if min_team_str is not None
                else None
            )

            requirements.append(
                RuleRequirement(
                    min_approvals=min_approvals,
                    team=team,
                    min_team=min_team,
                )
            )
        return requirements


class GovernanceConfigValidator:
    """Validator for verifying business rules against the repository state."""

    def __init__(self, config: GovernanceConfig, repo_root: Optional[str] = None):
        """Initializes the validator with a governance configuration and optional repo root."""
        self.config = config
        self.repo_root = repo_root

    def validate_overlaps(
        self, repo_path: Optional[str] = None
    ) -> List[ValidationError]:
        """Walks the repository's tracked files and returns a list of overlap errors."""
        resolved_path = repo_path or self.repo_root or os.getcwd()
        tracked_files = self._get_tracked_files(resolved_path)
        overlapping_files: Dict[str, List[str]] = {}

        for file_path in tracked_files:
            matched_rule_names = []
            for rule in self.config.rules:
                if rule.matches(file_path):
                    matched_rule_names.append(rule.name)

            if len(matched_rule_names) > 1:
                overlapping_files[file_path] = matched_rule_names

        errors = []
        for file, rules in overlapping_files.items():
            errors.append(
                ValidationError(
                    file_path=file,
                    message=f"File '{file}' matches multiple rules: {', '.join(rules)}",
                )
            )
        return errors

    def validate_no_fallback(
        self, repo_path: Optional[str] = None
    ) -> List[ValidationError]:
        """Walks the repository's tracked files and returns a list of errors for files falling into fallback rules."""
        resolved_path = repo_path or self.repo_root or os.getcwd()
        tracked_files = self._get_tracked_files(resolved_path)
        errors = []

        for file_path in tracked_files:
            matched_any = False
            for rule in self.config.rules:
                if rule.matches(file_path):
                    matched_any = True
                    break

            if not matched_any:
                errors.append(
                    ValidationError(
                        file_path=file_path,
                        message=f"File '{file_path}' does not match any governance rule (falls back to fallback requirements)",
                    )
                )

        return errors

    def _get_tracked_files(self, repo_path: str) -> List[str]:
        """Gets all tracked and staged files in the repository using git ls-files."""
        result = subprocess.run(
            [
                "git",
                "-C",
                repo_path,
                "ls-files",
                "--cached",
                "--others",
                "--exclude-standard",
            ],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            check=True,
        )
        return [
            Path(line.strip()).as_posix()
            for line in result.stdout.splitlines()
            if line.strip()
        ]
