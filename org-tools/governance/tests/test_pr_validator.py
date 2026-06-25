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

"""Unit tests for the pull request validator."""

import os
import sys
import unittest
from unittest.mock import MagicMock, patch

sys.path.insert(
    0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../scripts"))
)


# Mock the 'github' module before importing our script
class MockGithubException(Exception):
    def __init__(self, status=None, data=None, headers=None):
        super().__init__(f"Github error {status}: {data}")
        self.status = status
        self.data = data
        self.headers = headers


mock_github = MagicMock()
mock_github.GithubException = MockGithubException
sys.modules["github"] = mock_github


from pr_validator import (  # noqa: E402
    PullRequestValidator,
    GitHubClient,
    main,
    RepoName,
    REPO_RULES_MAPPING,
)
from pr_models import (  # noqa: E402
    MergeableReason,
    PullRequest,
    Review,
    ReviewState,
    TeamMemberships,
    ValidationErrorReason,
)
from governance_config_parser import (  # noqa: E402
    GovernanceConfig,
    GovernanceConfigParser,
    GovernanceRule,
    RuleRequirement,
    Team,
)


class TestPullRequestValidator(unittest.TestCase):
    """Tests for TestPullRequestValidator class."""

    def setUp(self):
        """Set up test fixtures."""
        # 1. Setup team hierarchy
        self.hierarchy = {
            "devops": Team(name="devops", level=1),
            "maintainers": Team(name="maintainers", level=2),
            "tech-council": Team(name="tech-council", level=3),
            "governance-council": Team(name="governance-council", level=4),
        }

        # 2. Setup rules
        self.rules = [
            GovernanceRule(
                name="Governance & Licensing",
                patterns=["LICENSE", ".github/CODEOWNERS"],
                requires_all=[
                    RuleRequirement(
                        min_approvals=1, team=self.hierarchy["governance-council"]
                    )
                ],
            ),
            GovernanceRule(
                name="Core Protocol Source",
                patterns=["source/**"],
                requires_all=[
                    RuleRequirement(
                        min_approvals=1, min_team=self.hierarchy["tech-council"]
                    )
                ],
            ),
        ]

        # 3. Setup fallback
        self.fallback = [
            RuleRequirement(min_approvals=1, min_team=self.hierarchy["maintainers"])
        ]

        # 4. Setup proxy reviewers
        self.proxy_reviewers = {"proxy1", "proxy2"}

        # 5. Setup config
        self.config = GovernanceConfig(
            teams=self.hierarchy,
            rules=self.rules,
            fallback=self.fallback,
            proxy_reviewers=self.proxy_reviewers,
        )

        # 6. Setup memberships
        self.memberships = TeamMemberships.create(
            members_by_team={
                "devops": {"dev1", "dev2"},
                "maintainers": {"maint1", "maint2", "tc-member1"},
                "tech-council": {"tc-member1", "tc-member2"},
                "governance-council": {
                    "gov-member1",
                    "gov-member2",
                    "proxy1",
                },
            },
            teams=self.hierarchy,
        )

        # 7. Setup validator
        self.validator = PullRequestValidator(self.config, self.memberships)

    def test_draft_pr_fails_quickly(self):
        """Test that draft pull requests fail validation quickly."""
        pr = PullRequest(
            number=1,
            author="author1",
            is_draft=True,
            changed_files=["source/main.py"],
            reviews=[],
        )
        res = self.validator.validate(pr)
        self.assertFalse(res.is_mergeable)
        self.assertEqual(res.error, ValidationErrorReason.DRAFT_PR)

    def test_no_changed_files_passes(self):
        """Test that pull requests with no changed files pass validation."""
        pr = PullRequest(
            number=1, author="author1", is_draft=False, changed_files=[], reviews=[]
        )
        res = self.validator.validate(pr)
        self.assertTrue(res.is_mergeable)
        self.assertEqual(res.mergeable_reason, MergeableReason.NO_CHANGED_FILES)

    def test_proxy_voter_override_passes(self):
        """Test that proxy voter overrides pass validation."""
        # Proxy override bypasses changes requested and missing approvals
        pr = PullRequest(
            number=1,
            author="author1",
            is_draft=False,
            changed_files=["source/main.py"],
            reviews=[
                Review(user="tc-member1", state=ReviewState.CHANGES_REQUESTED),
                Review(user="proxy1", state=ReviewState.APPROVED),
            ],
        )
        res = self.validator.validate(pr)
        self.assertTrue(res.is_mergeable)
        self.assertEqual(res.mergeable_reason, MergeableReason.PROXY_OVERRIDE)

    def test_standard_rule_success(self):
        """Test that standard rules are successfully validated."""
        pr = PullRequest(
            number=1,
            author="author1",
            is_draft=False,
            changed_files=["source/main.py"],
            reviews=[
                Review(user="tc-member1", state=ReviewState.APPROVED),
            ],
        )
        res = self.validator.validate(pr)
        self.assertTrue(res.is_mergeable)
        self.assertEqual(res.mergeable_reason, MergeableReason.RULES_SATISFIED)

    def test_insufficient_approvals_fails(self):
        """Test that validation fails if approvals are insufficient."""
        pr = PullRequest(
            number=1,
            author="author1",
            is_draft=False,
            changed_files=["source/main.py"],
            reviews=[
                Review(user="dev1", state=ReviewState.APPROVED),
            ],
        )
        res = self.validator.validate(pr)
        self.assertFalse(res.is_mergeable)
        self.assertEqual(res.error, ValidationErrorReason.INSUFFICIENT_APPROVALS)

    def test_fallback_applied_correctly(self):
        """Test that fallback rules are applied correctly."""
        # dev1 (level 1) approval should fail for fallback (needs level >= 2)
        pr = PullRequest(
            number=1,
            author="author1",
            is_draft=False,
            changed_files=["docs/index.md"],
            reviews=[
                Review(user="dev1", state=ReviewState.APPROVED),
            ],
        )
        res = self.validator.validate(pr)
        self.assertFalse(res.is_mergeable)
        self.assertEqual(res.error, ValidationErrorReason.INSUFFICIENT_APPROVALS)

        # maint1 (level 2) approval should pass
        pr_ok = PullRequest(
            number=1,
            author="author1",
            is_draft=False,
            changed_files=["docs/index.md"],
            reviews=[
                Review(user="maint1", state=ReviewState.APPROVED),
            ],
        )
        res_ok = self.validator.validate(pr_ok)
        self.assertTrue(res_ok.is_mergeable)
        self.assertEqual(res_ok.mergeable_reason, MergeableReason.RULES_SATISFIED)

    def test_venn_diagram_higher_level_counts(self):
        """Test that higher level approvals satisfy lower level requirements."""
        # gov-member1 (level 4) satisfies level >= 2 fallback requirement
        pr = PullRequest(
            number=1,
            author="author1",
            is_draft=False,
            changed_files=["docs/index.md"],
            reviews=[
                Review(user="gov-member1", state=ReviewState.APPROVED),
            ],
        )
        res = self.validator.validate(pr)
        self.assertTrue(res.is_mergeable)

    def test_specific_team_requirement(self):
        """Test validation of specific team requirements."""
        # tc-member1 (level 3) is not in governance-council, should fail
        pr = PullRequest(
            number=1,
            author="author1",
            is_draft=False,
            changed_files=["LICENSE"],
            reviews=[
                Review(user="tc-member1", state=ReviewState.APPROVED),
            ],
        )
        res = self.validator.validate(pr)
        self.assertFalse(res.is_mergeable)
        self.assertEqual(res.error, ValidationErrorReason.INSUFFICIENT_APPROVALS)

        # gov-member1 is in governance-council, should pass
        pr_ok = PullRequest(
            number=1,
            author="author1",
            is_draft=False,
            changed_files=["LICENSE"],
            reviews=[
                Review(user="gov-member1", state=ReviewState.APPROVED),
            ],
        )
        res_ok = self.validator.validate(pr_ok)
        self.assertTrue(res_ok.is_mergeable)

    def test_changes_requested_blocks(self):
        """Test that changes requested block validation."""
        pr = PullRequest(
            number=1,
            author="author1",
            is_draft=False,
            changed_files=["source/main.py"],
            reviews=[
                Review(user="tc-member1", state=ReviewState.APPROVED),
                Review(user="tc-member2", state=ReviewState.CHANGES_REQUESTED),
            ],
        )
        res = self.validator.validate(pr)
        self.assertFalse(res.is_mergeable)
        self.assertEqual(res.error, ValidationErrorReason.CHANGES_REQUESTED)
        self.assertEqual(len(res.requirement_statuses), 1)
        self.assertEqual(len(res.file_statuses), 1)

    def test_unauthorized_changes_requested_does_not_block(self):
        """Test that unauthorized changes requested do not block validation."""
        pr = PullRequest(
            number=1,
            author="author1",
            is_draft=False,
            changed_files=["source/main.py"],
            reviews=[
                Review(user="tc-member1", state=ReviewState.APPROVED),
                Review(user="dev1", state=ReviewState.CHANGES_REQUESTED),
            ],
        )
        res = self.validator.validate(pr)
        self.assertTrue(res.is_mergeable)

    def test_proxy_changes_requested_blocks(self):
        """Test that changes requested by a proxy reviewer block validation."""
        pr = PullRequest(
            number=1,
            author="author1",
            is_draft=False,
            changed_files=["source/main.py"],
            reviews=[
                Review(user="tc-member1", state=ReviewState.APPROVED),
                Review(user="proxy2", state=ReviewState.CHANGES_REQUESTED),
            ],
        )
        res = self.validator.validate(pr)
        self.assertFalse(res.is_mergeable)
        self.assertEqual(res.error, ValidationErrorReason.CHANGES_REQUESTED)
        self.assertEqual(len(res.requirement_statuses), 1)
        self.assertEqual(len(res.file_statuses), 1)

    def test_self_approval_restrictions(self):
        """Test restrictions on self-approval."""
        # Author tc-member1 cannot approve their own PR
        pr = PullRequest(
            number=1,
            author="tc-member1",
            is_draft=False,
            changed_files=["source/main.py"],
            reviews=[
                Review(user="tc-member1", state=ReviewState.APPROVED),
            ],
        )
        res = self.validator.validate(pr)
        self.assertFalse(res.is_mergeable)
        self.assertEqual(res.error, ValidationErrorReason.INSUFFICIENT_APPROVALS)

    def test_dismissed_reviews(self):
        """Test that dismissed reviews are handled correctly."""
        pr = PullRequest(
            number=1,
            author="author1",
            is_draft=False,
            changed_files=["source/main.py"],
            reviews=[
                Review(user="tc-member1", state=ReviewState.APPROVED),
                Review(user="tc-member1", state=ReviewState.DISMISSED),
            ],
        )
        res = self.validator.validate(pr)
        self.assertFalse(res.is_mergeable)

    def test_commented_reviews_ignored(self):
        """Test that commented reviews are ignored."""
        pr = PullRequest(
            number=1,
            author="author1",
            is_draft=False,
            changed_files=["source/main.py"],
            reviews=[
                Review(user="tc-member1", state=ReviewState.APPROVED),
                Review(user="tc-member1", state=ReviewState.COMMENTED),
            ],
        )
        res = self.validator.validate(pr)
        self.assertTrue(res.is_mergeable)

    def test_multi_level_requirement(self):
        """Test validation of multi-level requirements."""
        custom_rule = GovernanceRule(
            name="Venn Rule",
            patterns=["*"],
            requires_all=[
                RuleRequirement(
                    min_approvals=2, min_team=self.hierarchy["governance-council"]
                ),
                RuleRequirement(
                    min_approvals=4, min_team=self.hierarchy["maintainers"]
                ),
            ],
        )
        config = GovernanceConfig(
            teams=self.hierarchy,
            rules=[custom_rule],
            fallback=[],
            proxy_reviewers=set(),
        )
        validator = PullRequestValidator(config, self.memberships)

        # Case A: 2 level-4, 2 level-2 approvals (Total 4)
        # Under the Venn Diagram model, the 2 level-4 approvals count towards the level-2
        # requirement as well, satisfying both requirements with 4 total unique approvals.
        pr_ok_double_dip = PullRequest(
            number=1,
            author="author1",
            is_draft=False,
            changed_files=["file.txt"],
            reviews=[
                Review(user="gov-member1", state=ReviewState.APPROVED),
                Review(user="gov-member2", state=ReviewState.APPROVED),
                Review(user="maint1", state=ReviewState.APPROVED),
                Review(user="maint2", state=ReviewState.APPROVED),
            ],
        )
        res_ok_double_dip = validator.validate(pr_ok_double_dip)
        self.assertTrue(res_ok_double_dip.is_mergeable)

        # Case B: 3 level-4 approvals, total only 3 approvals.
        # Fails because total approvals (3) is less than the level-2 requirement (4).
        pr_fail_too_few = PullRequest(
            number=1,
            author="author1",
            is_draft=False,
            changed_files=["file.txt"],
            reviews=[
                Review(user="gov-member1", state=ReviewState.APPROVED),
                Review(user="gov-member2", state=ReviewState.APPROVED),
                Review(user="proxy1", state=ReviewState.APPROVED),
            ],
        )
        res_fail_too_few = validator.validate(pr_fail_too_few)
        self.assertFalse(res_fail_too_few.is_mergeable)
        self.assertEqual(
            res_fail_too_few.error, ValidationErrorReason.INSUFFICIENT_APPROVALS
        )

        # Case C: 2 level-4, 4 level-2 approvals (Total 6 unique, satisfies both)
        # 2 assigned to level-4, 4 assigned to level-2.
        pr_ok = PullRequest(
            number=1,
            author="author1",
            is_draft=False,
            changed_files=["file.txt"],
            reviews=[
                Review(user="gov-member1", state=ReviewState.APPROVED),
                Review(user="gov-member2", state=ReviewState.APPROVED),
                Review(user="maint1", state=ReviewState.APPROVED),
                Review(user="maint2", state=ReviewState.APPROVED),
                Review(user="tc-member1", state=ReviewState.APPROVED),
                Review(user="tc-member2", state=ReviewState.APPROVED),
            ],
        )
        res_ok = validator.validate(pr_ok)
        self.assertTrue(res_ok.is_mergeable)

    def test_requirement_status_reporting(self):
        """Test requirement status reporting in validation result."""
        # We check source/main.py (requires 1 from min_team tech-council)
        # We request tc-member2 to review (1 eligible reviewer assigned)
        # but have 0 approvals.
        pr = PullRequest(
            number=1,
            author="author1",
            is_draft=False,
            changed_files=["source/main.py"],
            reviews=[],
            assigned_user_names=["tc-member2"],
            assigned_team_names=[],
        )
        res = self.validator.validate(pr)
        self.assertFalse(res.is_mergeable)
        self.assertEqual(res.error, ValidationErrorReason.INSUFFICIENT_APPROVALS)
        self.assertEqual(len(res.requirement_statuses), 1)

        status = res.requirement_statuses[0]
        self.assertEqual(status.requirement.min_team, self.hierarchy["tech-council"])
        self.assertEqual(status.requirement.min_approvals, 1)
        self.assertEqual(status.approved_count, 0)
        self.assertEqual(status.assigned_count, 1)
        self.assertFalse(status.is_satisfied)

    def test_governance_config_parser(self):
        """Test parsing of governance configuration."""
        yaml_data = {
            "team_hierarchy": {
                "devops": 1,
                "maintainers": 2,
                "governance-council": 3,
            },
            "proxy_reviewers": ["proxy1"],
            "fallback": {"requires": [{"min_team": "maintainers", "min_approvals": 1}]},
            "rules": [
                {
                    "name": "Licensing",
                    "patterns": ["LICENSE"],
                    "requires": [{"team": "governance-council", "min_approvals": 2}],
                }
            ],
        }

        config = GovernanceConfigParser()._parse(yaml_data)

        self.assertEqual(
            config.teams,
            {
                "devops": Team("devops", 1),
                "maintainers": Team("maintainers", 2),
                "governance-council": Team("governance-council", 3),
            },
        )
        self.assertEqual(config.proxy_reviewers, {"proxy1"})

        self.assertEqual(len(config.fallback), 1)
        self.assertEqual(config.fallback[0].min_team, Team("maintainers", 2))
        self.assertEqual(config.fallback[0].min_approvals, 1)

        self.assertEqual(len(config.rules), 1)
        rule = config.rules[0]
        self.assertEqual(rule.name, "Licensing")
        self.assertEqual(rule.patterns, ["LICENSE"])
        self.assertEqual(len(rule.requires_all), 1)
        self.assertEqual(rule.requires_all[0].team, Team("governance-council", 3))
        self.assertEqual(rule.requires_all[0].min_approvals, 2)

    def test_wildcard_matching(self):
        """Test wildcard pattern matching."""
        # Test 1: Recursive Glob pattern
        rule_recursive = GovernanceRule(
            name="Recursive", patterns=["source/**/*.py"], requires_all=[]
        )
        self.assertTrue(rule_recursive.matches("source/main.py"))
        self.assertTrue(rule_recursive.matches("source/a/b/c/main.py"))
        self.assertFalse(rule_recursive.matches("other/main.py"))

        # Test 2: Shallow Glob pattern
        rule_shallow = GovernanceRule(
            name="Shallow", patterns=["source/*.py"], requires_all=[]
        )
        self.assertTrue(rule_shallow.matches("source/main.py"))
        self.assertFalse(rule_shallow.matches("source/a/main.py"))
        self.assertFalse(rule_shallow.matches("main.py"))

    def test_rule_excludes(self):
        """Test rule pattern exclusion matching."""
        # Rule A matches source/** but excludes source/special/**
        rule = GovernanceRule(
            name="Source Rule",
            patterns=["source/**"],
            requires_all=[
                RuleRequirement(
                    min_approvals=1, min_team=self.hierarchy["tech-council"]
                )
            ],
            excluded_patterns=["source/special/**"],
        )
        config = GovernanceConfig(
            teams=self.hierarchy,
            rules=[rule],
            fallback=[],
            proxy_reviewers=set(),
        )
        validator = PullRequestValidator(config, self.memberships)

        # Case A: Matches source/main.py (not excluded)
        pr_ok = PullRequest(
            number=1,
            author="author1",
            is_draft=False,
            changed_files=["source/main.py"],
            reviews=[Review(user="tc-member1", state=ReviewState.APPROVED)],
        )
        res_ok = validator.validate(pr_ok)
        self.assertTrue(res_ok.is_mergeable)

        # Case B: Excluded source/special/helper.py (should use fallback rule)
        config_with_fallback = GovernanceConfig(
            teams=self.hierarchy,
            rules=[rule],
            fallback=[
                RuleRequirement(min_approvals=1, min_team=self.hierarchy["maintainers"])
            ],
            proxy_reviewers=set(),
        )
        validator_with_fallback = PullRequestValidator(
            config_with_fallback, self.memberships
        )

        pr_excluded_fail = PullRequest(
            number=1,
            author="author1",
            is_draft=False,
            changed_files=["source/special/helper.py"],
            reviews=[
                Review(user="dev1", state=ReviewState.APPROVED)
            ],  # dev1 (L1) not enough for L2 fallback
        )
        res_excluded_fail = validator_with_fallback.validate(pr_excluded_fail)
        self.assertFalse(res_excluded_fail.is_mergeable)
        self.assertEqual(
            res_excluded_fail.error, ValidationErrorReason.INSUFFICIENT_APPROVALS
        )

    def test_merge_requirements_multiple_rules(self):
        """Test that requirements from multiple rules are merged by taking the maximum approvals needed."""
        # Rule 1 (devops-rule): needs 2 devops approvals
        # Rule 2 (central-rule): needs 1 devops approval and 1 tech-council approval
        # Merged requirements should be: 2 devops approvals and 1 tech-council approval.
        pr = PullRequest(
            number=1,
            author="author1",
            is_draft=False,
            # Changed files matching both rules
            changed_files=["source/ops/deploy.sh", "source/central/core.py"],
            reviews=[
                # 2 devops approvals
                Review(user="dev1", state=ReviewState.APPROVED),
                Review(user="dev2", state=ReviewState.APPROVED),
                # 1 tech-council approval
                Review(user="tc-member1", state=ReviewState.APPROVED),
            ],
        )
        res = self.validator.validate(pr)
        self.assertTrue(res.is_mergeable)
        self.assertEqual(res.mergeable_reason, MergeableReason.RULES_SATISFIED)

    def test_one_approved_one_changes_requested_assigned_count(self):
        """Test that a user who has requested changes counts towards assigned_count, while an approver does not."""
        # 1. Setup a custom hierarchy and config requiring 2 approvals
        hierarchy = {
            "maintainers": Team(name="maintainers", level=2),
        }
        rules = [
            GovernanceRule(
                name="Test Rule",
                patterns=["*"],
                requires_all=[
                    RuleRequirement(min_approvals=2, min_team=hierarchy["maintainers"])
                ],
            )
        ]
        config = GovernanceConfig(
            teams=hierarchy,
            rules=rules,
            fallback=[],
            proxy_reviewers=set(),
        )
        memberships = TeamMemberships.create(
            members_by_team={
                "maintainers": {"maint1", "maint2", "maint3"},
            },
            teams=hierarchy,
        )
        validator = PullRequestValidator(config, memberships)

        # PR where:
        # - maint1 has approved
        # - maint2 has requested changes
        # both are in 'maintainers'.
        pr = PullRequest(
            number=1,
            author="author1",
            is_draft=False,
            changed_files=["file.txt"],
            reviews=[
                Review(user="maint1", state=ReviewState.APPROVED),
                Review(user="maint2", state=ReviewState.CHANGES_REQUESTED),
            ],
        )

        res = validator.validate(pr)
        self.assertFalse(res.is_mergeable)
        self.assertEqual(res.error, ValidationErrorReason.CHANGES_REQUESTED)

        self.assertEqual(len(res.requirement_statuses), 1)
        status = res.requirement_statuses[0]
        self.assertEqual(status.requirement.min_team, hierarchy["maintainers"])
        self.assertEqual(status.requirement.min_approvals, 2)
        self.assertEqual(status.approved_count, 1)
        self.assertEqual(
            status.assigned_count, 1
        )  # Only maint2 is assigned/active and not approved
        self.assertFalse(status.is_satisfied)
        self.assertEqual(status.approvers, ["maint1"])


class TestFetchTeamMemberships(unittest.TestCase):
    """Tests for GitHubClient.fetch_team_memberships method."""

    def test_fetch_success(self):
        """Test fetch_team_memberships successfully fetches team memberships."""
        mock_github = MagicMock()
        mock_org = MagicMock()
        mock_github.get_organization.return_value = mock_org

        mock_team1 = MagicMock()
        mock_member1 = MagicMock()
        mock_member1.login = "user1"
        mock_member2 = MagicMock()
        mock_member2.login = "user2"
        mock_team1.get_members.return_value = [mock_member1, mock_member2]

        mock_team2 = MagicMock()
        mock_member3 = MagicMock()
        mock_member3.login = "user3"
        mock_team2.get_members.return_value = [mock_member3]

        def get_team_side_effect(slug):
            if slug == "devops":
                return mock_team1
            elif slug == "maintainers":
                return mock_team2
            raise MockGithubException(status=404, data={"message": "Not Found"})

        mock_org.get_team_by_slug.side_effect = get_team_side_effect

        config = GovernanceConfig(
            teams={
                "devops": Team("devops", 1),
                "maintainers": Team("maintainers", 2),
            },
            rules=[],
            fallback=[],
            proxy_reviewers=set(),
        )

        github_client = GitHubClient(mock_github)
        memberships = github_client.fetch_team_memberships("my-org", config)

        self.assertEqual(
            memberships.members_by_team,
            {
                Team("devops", 1): {"user1", "user2"},
                Team("maintainers", 2): {"user3"},
            },
        )
        mock_github.get_organization.assert_called_once_with("my-org")

    def test_fetch_org_fails(self):
        """Test fetch_team_memberships raises RuntimeError when org fetch fails."""
        mock_github = MagicMock()
        mock_github.get_organization.side_effect = MockGithubException(
            status=404, data={"message": "Org Not Found"}
        )

        config = GovernanceConfig(
            teams={"devops": Team("devops", 1)},
            rules=[],
            fallback=[],
            proxy_reviewers=set(),
        )

        github_client = GitHubClient(mock_github)
        with self.assertRaises(RuntimeError) as ctx:
            github_client.fetch_team_memberships("my-org", config)

        self.assertIn("Failed to fetch organization 'my-org'", str(ctx.exception))

    def test_fetch_team_fails(self):
        """Test fetch_team_memberships raises RuntimeError when a team fetch fails."""
        mock_github = MagicMock()
        mock_org = MagicMock()
        mock_github.get_organization.return_value = mock_org

        mock_org.get_team_by_slug.side_effect = MockGithubException(
            status=404, data={"message": "Team Not Found"}
        )

        config = GovernanceConfig(
            teams={"devops": Team("devops", 1)},
            rules=[],
            fallback=[],
            proxy_reviewers=set(),
        )

        github_client = GitHubClient(mock_github)
        with self.assertRaises(RuntimeError) as ctx:
            github_client.fetch_team_memberships("my-org", config)

        self.assertIn("Could not fetch members for team 'devops'", str(ctx.exception))


class TestPRValidatorMain(unittest.TestCase):
    """Tests for the main function of pr_validator."""

    @patch("pr_validator.sys.exit")
    @patch("pr_validator.print")
    @patch("pr_validator.argparse.ArgumentParser.parse_args")
    def test_main_invalid_repo_name(self, mock_parse_args, mock_print, mock_exit):
        """Test main fails when repo name is invalid."""
        mock_args = MagicMock()
        mock_args.repo = "Universal-Commerce-Protocol/invalid-repo"
        mock_parse_args.return_value = mock_args
        mock_exit.side_effect = SystemExit(1)

        with self.assertRaises(SystemExit) as cm:
            main()

        self.assertEqual(cm.exception.code, 1)
        mock_exit.assert_called_once_with(1)
        mock_print.assert_any_call(
            "❌ ERROR: Invalid repository name 'Universal-Commerce-Protocol/invalid-repo'. Must be one of: ['Universal-Commerce-Protocol/python-sdk']",
            file=sys.stderr,
        )

    @patch("pr_validator.sys.exit")
    @patch("pr_validator.ValidationLogger")
    @patch("pr_validator.PullRequestValidator")
    @patch("pr_validator.GitHubClient")
    @patch("pr_validator.Github")
    @patch("pr_validator.Auth.Token")
    @patch("pr_validator.GovernanceConfigParser")
    @patch("pr_validator.argparse.ArgumentParser.parse_args")
    def test_main_valid_repo_name(
        self,
        mock_parse_args,
        mock_parser_class,
        mock_token,
        mock_github_class,
        mock_github_client_class,
        mock_validator_class,
        mock_logger_class,
        mock_exit,
    ):
        """Test main succeeds and parses file with valid repo name."""
        mock_args = MagicMock()
        mock_args.token = "token"
        mock_args.org = "org"
        mock_args.repo = "Universal-Commerce-Protocol/python-sdk"
        mock_args.pr = 123
        mock_parse_args.return_value = mock_args
        mock_exit.side_effect = SystemExit(0)

        # Mock parse_file to return a dummy config
        mock_parser = MagicMock()
        mock_parser_class.return_value = mock_parser
        dummy_config = MagicMock()
        mock_parser.parse_file.return_value = dummy_config

        # Mock gateway
        mock_gateway = MagicMock()
        mock_github_client_class.return_value = mock_gateway

        # Mock validation result to be mergeable
        mock_validator = MagicMock()
        mock_validator_class.return_value = mock_validator
        mock_result = MagicMock()
        mock_result.is_mergeable = True
        mock_result.mergeable_reason = None
        mock_validator.validate.return_value = mock_result

        with self.assertRaises(SystemExit) as cm:
            main()

        self.assertEqual(cm.exception.code, 0)
        # Check parse_file was called with the mapped rules file
        mock_parser.parse_file.assert_called_once_with(
            REPO_RULES_MAPPING[RepoName.PYTHON_SDK]
        )
        mock_exit.assert_called_once_with(0)


if __name__ == "__main__":
    unittest.main()
