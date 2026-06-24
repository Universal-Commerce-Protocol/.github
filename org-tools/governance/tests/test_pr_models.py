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

"""Unit tests for the Pull Request dataclasses and models."""

import os
import sys
import unittest

sys.path.insert(
    0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../scripts"))
)

from pr_models import (
    PullRequest,
    Review,
    ReviewState,
    TeamMemberships,
    RuleRequirement,
    Team,
    RequirementTargetType,
    merge_requirements,
)


class TestPRModels(unittest.TestCase):
    """Tests for the lowercase normalization in PR models."""

    def test_review_lowercase_normalization(self):
        """Test that Review user names are normalized to lowercase."""
        review = Review.create(user="ALICE", state=ReviewState.APPROVED)
        self.assertEqual(review.user, "alice")

    def test_pull_request_lowercase_normalization(self):
        """Test that PullRequest fields are normalized to lowercase."""
        review_input = Review.create(user="Bob", state=ReviewState.APPROVED)
        pr = PullRequest.create(
            number=42,
            author="CHARLIE",
            is_draft=False,
            changed_files=["README.md"],
            reviews=[review_input],
            assigned_user_names=["Dave", "EVE"],
            assigned_team_names=["Tech-Council", "ADMINS"],
        )

        expected = PullRequest(
            number=42,
            author="charlie",
            is_draft=False,
            changed_files=["README.md"],
            reviews=[Review(user="bob", state=ReviewState.APPROVED)],
            assigned_user_names=["dave", "eve"],
            assigned_team_names=["tech-council", "admins"],
        )
        self.assertEqual(expected, pr)

    def test_team_memberships_lowercase_normalization(self):
        """Test that TeamMemberships keys and member sets are normalized to lowercase."""
        memberships = TeamMemberships.create(
            members_by_team={
                "Tech-Council": {"Alice", "BOB"},
                "ADMINS": {"charlie", "Dave"},
            }
        )
        self.assertEqual(
            memberships.members_by_team,
            {
                "tech-council": {"alice", "bob"},
                "admins": {"charlie", "dave"},
            },
        )

    def test_merge_requirements(self):
        """Test that merge_requirements correctly merges requirements."""
        team_devops = Team.create(name="devops", level=1)
        team_admin = Team.create(name="admins", level=2)

        req1 = RuleRequirement(min_approvals=1, team=team_devops)
        req2 = RuleRequirement(min_approvals=3, team=team_devops)
        req3 = RuleRequirement(min_approvals=2, team=team_admin)

        merged = merge_requirements([req1, req2, req3])

        self.assertEqual(len(merged), 2)

        devops_req = next(r for r in merged if r.team == team_devops)
        admin_req = next(r for r in merged if r.team == team_admin)

        self.assertEqual(devops_req.min_approvals, 3)
        self.assertEqual(admin_req.min_approvals, 2)
        self.assertEqual(devops_req.target_key, (RequirementTargetType.TEAM, "devops"))
        self.assertEqual(admin_req.target_key, (RequirementTargetType.TEAM, "admins"))


if __name__ == "__main__":
    unittest.main()
