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

"""Unit tests for the ValidationLogger class."""

import os
import sys
import unittest
from unittest.mock import patch

sys.path.insert(
    0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../scripts"))
)

from pr_models import (
    FileValidationStatus,
    MergeableReason,
    RequirementStatus,
    ValidationErrorReason,
    ValidationResult,
)
from governance_config_parser import RuleRequirement, Team
from validation_logger import ValidationLogger

HELP_SUFFIX = (
    "\n"
    "\n"
    "---\n"
    "\n"
    "💡 **Need help?** For a detailed explanation of this report and how to resolve "
    "failures, see the [Governance Gate Validation Guide](https://github.com/Universal-Commerce-Protocol/.github/blob/main/org-tools/governance/docs/validation_report.md).\n"
    "\n"
    "If you suspect a bug or issue with this validator script, please "
    "[report an issue in the .github repository](https://github.com/Universal-Commerce-Protocol/.github/issues)."
)


class TestValidationLogger(unittest.TestCase):
    """Tests for ValidationLogger class."""

    @patch("builtins.open", new_callable=unittest.mock.mock_open)
    def test_mergeable_no_changed_files(self, mock_open):
        """Test summary output when PR is mergeable due to no changed files."""
        res = ValidationResult(
            is_mergeable=True,
            mergeable_reason=MergeableReason.NO_CHANGED_FILES,
        )
        logger = ValidationLogger(res)
        logger.write_summary("dummy.txt")

        mock_open.assert_called_once_with("dummy.txt", "w", encoding="utf-8")
        handle = mock_open()
        written_content = "".join(call.args[0] for call in handle.write.call_args_list)

        expected = (
            "# ⚖️ Governance Gate Validation Report\n"
            "\n"
            "## 🟢 SUCCESS: No changed files in this Pull Request."
        )
        self.assertEqual(expected, written_content)

    @patch("builtins.open", new_callable=unittest.mock.mock_open)
    def test_mergeable_proxy_override(self, mock_open):
        """Test summary output when PR is mergeable due to proxy override."""
        res = ValidationResult(
            is_mergeable=True,
            mergeable_reason=MergeableReason.PROXY_OVERRIDE,
        )
        logger = ValidationLogger(res)
        logger.write_summary("dummy.txt")

        mock_open.assert_called_once_with("dummy.txt", "w", encoding="utf-8")
        handle = mock_open()
        written_content = "".join(call.args[0] for call in handle.write.call_args_list)

        expected = (
            "# ⚖️ Governance Gate Validation Report\n"
            "\n"
            "## 🟢 SUCCESS: Emergency override exception approved by Proxy Reviewer."
        )
        self.assertEqual(expected, written_content)

    @patch("builtins.open", new_callable=unittest.mock.mock_open)
    def test_mergeable_rules_satisfied(self, mock_open):
        """Test summary output when PR is mergeable due to rules satisfied."""
        res = ValidationResult(
            is_mergeable=True,
            mergeable_reason=MergeableReason.RULES_SATISFIED,
        )
        logger = ValidationLogger(res)
        logger.write_summary("dummy.txt")

        mock_open.assert_called_once_with("dummy.txt", "w", encoding="utf-8")
        handle = mock_open()
        written_content = "".join(call.args[0] for call in handle.write.call_args_list)

        expected = (
            "# ⚖️ Governance Gate Validation Report\n"
            "\n"
            "## 🟢 SUCCESS: All governance rules satisfied."
        )
        self.assertEqual(expected, written_content)

    @patch("builtins.open", new_callable=unittest.mock.mock_open)
    def test_error_draft_pr(self, mock_open):
        """Test summary output when PR validation fails due to draft status."""
        res = ValidationResult(
            is_mergeable=False,
            error=ValidationErrorReason.DRAFT_PR,
        )
        logger = ValidationLogger(res)
        logger.write_summary("dummy.txt")

        mock_open.assert_called_once_with("dummy.txt", "w", encoding="utf-8")
        handle = mock_open()
        written_content = "".join(call.args[0] for call in handle.write.call_args_list)

        expected = (
            "# ⚖️ Governance Gate Validation Report\n"
            "\n"
            "## 🔴 FAILURE: Pull Request is in draft status."
        ) + HELP_SUFFIX
        self.assertEqual(expected, written_content)

    @patch("builtins.open", new_callable=unittest.mock.mock_open)
    def test_error_changes_requested(self, mock_open):
        """Test summary output when PR validation fails due to changes requested."""
        res = ValidationResult(
            is_mergeable=False,
            error=ValidationErrorReason.CHANGES_REQUESTED,
        )
        logger = ValidationLogger(res)
        logger.write_summary("dummy.txt")

        mock_open.assert_called_once_with("dummy.txt", "w", encoding="utf-8")
        handle = mock_open()
        written_content = "".join(call.args[0] for call in handle.write.call_args_list)

        expected = (
            "# ⚖️ Governance Gate Validation Report\n"
            "\n"
            "## 🔴 FAILURE: An authorized reviewer has requested changes."
        ) + HELP_SUFFIX
        self.assertEqual(expected, written_content)

    @patch("builtins.open", new_callable=unittest.mock.mock_open)
    def test_error_insufficient_approvals_summary(self, mock_open):
        """Test summary message when PR has insufficient approvals."""
        team = Team(name="tech-council", level=3)
        req = RuleRequirement(min_approvals=2, team=team)
        status = RequirementStatus(
            requirement=req,
            approved_count=1,
            assigned_count=0,
            is_satisfied=False,
        )
        res = ValidationResult(
            is_mergeable=False,
            error=ValidationErrorReason.INSUFFICIENT_APPROVALS,
            requirement_statuses=[status],
        )
        logger = ValidationLogger(res)
        logger.write_summary("dummy.txt")

        mock_open.assert_called_once_with("dummy.txt", "w", encoding="utf-8")
        handle = mock_open()
        written_content = "".join(call.args[0] for call in handle.write.call_args_list)

        expected = (
            "# ⚖️ Governance Gate Validation Report\n"
            "\n"
            "## 🔴 FAILURE: Insufficient approvals.\n"
            "---\n"
            "\n"
            "### 🌍 1. GLOBAL PR SUMMARY\n"
            "\n"
            "Merged requirements across all changed files:\n"
            "\n"
            "* **2 approvals** from team 'tech-council'\n"
            "  * **Met:** 🔴 No (1/2 approved)\n"
            "  * **Pending:** Needs 1 approval from team 'tech-council' (0 eligible reviewers assigned). "
            "Waiting for 1 more reviewer(s) to be assigned from team 'tech-council'.\n"
        ) + HELP_SUFFIX
        self.assertEqual(expected, written_content)

    @patch("builtins.open", new_callable=unittest.mock.mock_open)
    def test_write_summary_waiting_for_approval(self, mock_open):
        """Test write_summary outputs 'Waiting for approval' when reviewers are assigned."""
        team = Team(name="tech-council", level=3)
        req = RuleRequirement(min_approvals=2, team=team)
        status = RequirementStatus(
            requirement=req,
            approved_count=1,
            assigned_count=1,  # 1 approved + 1 assigned = 2 (meets min_approvals)
            is_satisfied=False,
        )
        res = ValidationResult(
            is_mergeable=False,
            error=ValidationErrorReason.INSUFFICIENT_APPROVALS,
            requirement_statuses=[status],
        )
        logger = ValidationLogger(res)
        logger.write_summary("dummy.txt")

        mock_open.assert_called_once_with("dummy.txt", "w", encoding="utf-8")
        handle = mock_open()
        written_content = "".join(call.args[0] for call in handle.write.call_args_list)

        expected = (
            "# ⚖️ Governance Gate Validation Report\n"
            "\n"
            "## 🔴 FAILURE: Insufficient approvals.\n"
            "---\n"
            "\n"
            "### 🌍 1. GLOBAL PR SUMMARY\n"
            "\n"
            "Merged requirements across all changed files:\n"
            "\n"
            "* **2 approvals** from team 'tech-council'\n"
            "  * **Met:** 🔴 No (1/2 approved)\n"
            "  * **Pending:** Needs 1 approval from team 'tech-council' (1 eligible reviewer assigned). "
            "Waiting for approval from team 'tech-council'.\n"
        ) + HELP_SUFFIX
        self.assertEqual(expected, written_content)

    @patch("builtins.open", new_callable=unittest.mock.mock_open)
    def test_write_summary_assign_more_reviewers(self, mock_open):
        """Test write_summary outputs 'Assign X more reviewers' when not enough are assigned."""
        team = Team(name="tech-council", level=3)
        req = RuleRequirement(min_approvals=2, team=team)
        status = RequirementStatus(
            requirement=req,
            approved_count=0,
            assigned_count=1,  # 0 approved + 1 assigned = 1 (needs 1 more assigned)
            is_satisfied=False,
        )
        res = ValidationResult(
            is_mergeable=False,
            error=ValidationErrorReason.INSUFFICIENT_APPROVALS,
            requirement_statuses=[status],
        )
        logger = ValidationLogger(res)
        logger.write_summary("dummy.txt")

        mock_open.assert_called_once_with("dummy.txt", "w", encoding="utf-8")
        handle = mock_open()
        written_content = "".join(call.args[0] for call in handle.write.call_args_list)

        expected = (
            "# ⚖️ Governance Gate Validation Report\n"
            "\n"
            "## 🔴 FAILURE: Insufficient approvals.\n"
            "---\n"
            "\n"
            "### 🌍 1. GLOBAL PR SUMMARY\n"
            "\n"
            "Merged requirements across all changed files:\n"
            "\n"
            "* **2 approvals** from team 'tech-council'\n"
            "  * **Met:** 🔴 No (0/2 approved)\n"
            "  * **Pending:** Needs 2 approvals from team 'tech-council' (1 eligible reviewer assigned). "
            "Waiting for 1 more reviewer(s) to be assigned from team 'tech-council'.\n"
        ) + HELP_SUFFIX
        self.assertEqual(expected, written_content)

    @patch("builtins.open", new_callable=unittest.mock.mock_open)
    def test_write_summary_with_approvers(self, mock_open):
        """Test write_summary outputs approver details for partially filled slots."""
        team = Team(name="tech-council", level=3)
        req = RuleRequirement(min_approvals=2, team=team)
        status = RequirementStatus(
            requirement=req,
            approved_count=1,
            assigned_count=1,
            is_satisfied=False,
            approvers=["alice"],
        )
        res = ValidationResult(
            is_mergeable=False,
            error=ValidationErrorReason.INSUFFICIENT_APPROVALS,
            requirement_statuses=[status],
        )
        logger = ValidationLogger(res)
        logger.write_summary("dummy.txt")

        mock_open.assert_called_once_with("dummy.txt", "w", encoding="utf-8")
        handle = mock_open()
        written_content = "".join(call.args[0] for call in handle.write.call_args_list)

        expected = (
            "# ⚖️ Governance Gate Validation Report\n"
            "\n"
            "## 🔴 FAILURE: Insufficient approvals.\n"
            "---\n"
            "\n"
            "### 🌍 1. GLOBAL PR SUMMARY\n"
            "\n"
            "Merged requirements across all changed files:\n"
            "\n"
            "* **2 approvals** from team 'tech-council'\n"
            "  * **Met:** 🔴 No (1/2 approved - approved by: alice)\n"
            "  * **Pending:** Needs 1 approval from team 'tech-council' (1 eligible reviewer assigned). "
            "Waiting for approval from team 'tech-council'.\n"
        ) + HELP_SUFFIX
        self.assertEqual(expected, written_content)

    @patch("builtins.open", new_callable=unittest.mock.mock_open)
    def test_write_summary_satisfied_requirement_omits_pending(self, mock_open):
        """Test write_summary omits the pending/unmet line entirely when requirement is satisfied."""
        team = Team(name="tech-council", level=3)
        req = RuleRequirement(min_approvals=2, team=team)
        status = RequirementStatus(
            requirement=req,
            approved_count=2,
            assigned_count=0,
            is_satisfied=True,
            approvers=["alice", "bob"],
        )
        res = ValidationResult(
            is_mergeable=True,
            mergeable_reason=MergeableReason.RULES_SATISFIED,
            requirement_statuses=[status],
        )
        logger = ValidationLogger(res)
        logger.write_summary("dummy.txt")

        mock_open.assert_called_once_with("dummy.txt", "w", encoding="utf-8")
        handle = mock_open()
        written_content = "".join(call.args[0] for call in handle.write.call_args_list)

        expected = (
            "# ⚖️ Governance Gate Validation Report\n"
            "\n"
            "## 🟢 SUCCESS: All governance rules satisfied.\n"
            "---\n"
            "\n"
            "### 🌍 1. GLOBAL PR SUMMARY\n"
            "\n"
            "Merged requirements across all changed files:\n"
            "\n"
            "* **2 approvals** from team 'tech-council'\n"
            "  * **Met:** 🟢 Yes (2/2 approved - approved by: alice, bob)\n"
        )
        self.assertEqual(expected, written_content)

    @patch("builtins.open", new_callable=unittest.mock.mock_open)
    def test_write_summary_with_file_statuses(self, mock_open):
        """Test write_summary fully formats the file-by-file breakdown section."""
        team = Team(name="tech-council", level=3)
        req = RuleRequirement(min_approvals=2, team=team)

        status_satisfied = RequirementStatus(
            requirement=req,
            approved_count=2,
            assigned_count=0,
            is_satisfied=True,
            approvers=["alice", "bob"],
        )

        status_unsatisfied = RequirementStatus(
            requirement=req,
            approved_count=0,
            assigned_count=1,
            is_satisfied=False,
        )

        file_status_ok = FileValidationStatus(
            file_path="src/main.py",
            requirement_statuses=[status_satisfied],
            is_satisfied=True,
        )

        file_status_pending = FileValidationStatus(
            file_path="src/auth.py",
            requirement_statuses=[status_unsatisfied],
            is_satisfied=False,
        )

        res = ValidationResult(
            is_mergeable=False,
            error=ValidationErrorReason.INSUFFICIENT_APPROVALS,
            requirement_statuses=[status_unsatisfied],
            file_statuses=[file_status_ok, file_status_pending],
        )
        logger = ValidationLogger(res)
        logger.write_summary("dummy.txt")

        mock_open.assert_called_once_with("dummy.txt", "w", encoding="utf-8")
        handle = mock_open()
        written_content = "".join(call.args[0] for call in handle.write.call_args_list)

        expected = (
            "# ⚖️ Governance Gate Validation Report\n"
            "\n"
            "## 🔴 FAILURE: Insufficient approvals.\n"
            "---\n"
            "\n"
            "### 🌍 1. GLOBAL PR SUMMARY\n"
            "\n"
            "Merged requirements across all changed files:\n"
            "\n"
            "* **2 approvals** from team 'tech-council'\n"
            "  * **Met:** 🔴 No (0/2 approved)\n"
            "  * **Pending:** Needs 2 approvals from team 'tech-council' (1 eligible reviewer assigned). "
            "Waiting for 1 more reviewer(s) to be assigned from team 'tech-council'.\n"
            "\n"
            "\n"
            "---\n"
            "\n"
            "### 📂 2. FILE-BY-FILE BREAKDOWN\n"
            "\n"
            "* **File:** `src/main.py`\n"
            "  * **Status:** 🟢 SATISFIED\n"
            "  * **Requirements:**\n"
            "    * **2 approvals** from team 'tech-council'\n"
            "      * **Met:** 🟢 Yes (2/2 approved - approved by: alice, bob)\n"
            "\n"
            "* **File:** `src/auth.py`\n"
            "  * **Status:** 🔴 UNSATISFIED\n"
            "  * **Requirements:**\n"
            "    * **2 approvals** from team 'tech-council'\n"
            "      * **Met:** 🔴 No (0/2 approved)\n"
            "      * **Pending:** Needs 2 approvals from team 'tech-council' (1 eligible reviewer assigned). "
            "Waiting for 1 more reviewer(s) to be assigned from team 'tech-council'.\n"
        ) + HELP_SUFFIX
        self.assertEqual(expected, written_content)

    @patch("builtins.open", new_callable=unittest.mock.mock_open)
    def test_write_summary_with_hierarchical_clearance(self, mock_open):
        """Test write_summary outputs correct terminology for hierarchical clearance rules."""
        min_team = Team(name="tech-council", level=3)
        req = RuleRequirement(min_approvals=1, min_team=min_team)
        status = RequirementStatus(
            requirement=req,
            approved_count=0,
            assigned_count=0,
            is_satisfied=False,
        )
        res = ValidationResult(
            is_mergeable=False,
            error=ValidationErrorReason.INSUFFICIENT_APPROVALS,
            requirement_statuses=[status],
        )
        logger = ValidationLogger(res)
        logger.write_summary("dummy.txt")

        mock_open.assert_called_once_with("dummy.txt", "w", encoding="utf-8")
        handle = mock_open()
        written_content = "".join(call.args[0] for call in handle.write.call_args_list)

        expected = (
            "# ⚖️ Governance Gate Validation Report\n"
            "\n"
            "## 🔴 FAILURE: Insufficient approvals.\n"
            "---\n"
            "\n"
            "### 🌍 1. GLOBAL PR SUMMARY\n"
            "\n"
            "Merged requirements across all changed files:\n"
            "\n"
            "* **1 approval** from team 'tech-council' or higher in the UCP governance hierarchy\n"
            "  * **Met:** 🔴 No (0/1 approved)\n"
            "  * **Pending:** Needs 1 approval from team 'tech-council' or higher in the UCP governance hierarchy "
            "(0 eligible reviewers assigned). Waiting for 1 more reviewer(s) to be assigned from team "
            "'tech-council' or higher in the UCP governance hierarchy.\n"
        ) + HELP_SUFFIX
        self.assertEqual(expected, written_content)


if __name__ == "__main__":
    unittest.main()
