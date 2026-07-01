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

"""ValidationLogger for formatting and writing PR validation summaries in Markdown."""

from pr_models import (
    MergeableReason,
    RequirementStatus,
    ValidationErrorReason,
    ValidationResult,
)


class ValidationLogger:
    """Logs the validation result and creates the summary file."""

    GUIDE_URL = (
        "https://github.com/Universal-Commerce-Protocol/.github/blob/main/"
        "org-tools/governance/docs/validation_report.md"
    )
    ISSUE_URL = "https://github.com/Universal-Commerce-Protocol/.github/issues"

    def __init__(self, result: ValidationResult):
        self.result = result

    def write_summary(self, filename: str = "summary.txt") -> None:
        """Writes the summary and detailed result to the specified file."""
        report = self.generate_report()
        with open(filename, "w", encoding="utf-8") as f:
            f.write(report)

    def generate_report(self) -> str:
        """Generates a beautiful Markdown validation report."""
        lines = []
        lines.append("# ⚖️ Governance Gate Validation Report")
        lines.append("")

        # Overall Status Header
        if self.result.is_mergeable:
            if self.result.mergeable_reason == MergeableReason.NO_CHANGED_FILES:
                lines.append("## 🟢 SUCCESS: No changed files in this Pull Request.")
            elif self.result.mergeable_reason == MergeableReason.PROXY_OVERRIDE:
                lines.append(
                    "## 🟢 SUCCESS: Emergency override exception approved by Proxy Reviewer."
                )
            else:
                lines.append("## 🟢 SUCCESS: All governance rules satisfied.")
        else:
            if self.result.error == ValidationErrorReason.DRAFT_PR:
                lines.append("## 🔴 FAILURE: Pull Request is in draft status.")
            elif self.result.error == ValidationErrorReason.CHANGES_REQUESTED:
                lines.append(
                    "## 🔴 FAILURE: An authorized reviewer has requested changes."
                )
            elif self.result.error == ValidationErrorReason.INSUFFICIENT_APPROVALS:
                lines.append("## 🔴 FAILURE: Insufficient approvals.")
            else:
                lines.append("## 🔴 FAILURE: Unknown validation failure.")

        # 1. Global PR Summary
        if self.result.requirement_statuses:
            lines.append("---")
            lines.append("")
            lines.append("### 🌍 1. GLOBAL PR SUMMARY")
            lines.append("")
            lines.append("Merged requirements across all changed files:")
            lines.append("")
            for status in self.result.requirement_statuses:
                lines.append(self._format_requirement_status(status, indent=""))
                lines.append("")

        # 2. File-by-File Breakdown
        if self.result.file_statuses:
            lines.append("")
            lines.append("---")
            lines.append("")
            lines.append("### 📂 2. FILE-BY-FILE BREAKDOWN")
            lines.append("")
            for f_status in self.result.file_statuses:
                status_icon = (
                    "🟢 SATISFIED" if f_status.is_satisfied else "🔴 UNSATISFIED"
                )
                lines.append(f"* **File:** `{f_status.file_path}`")
                lines.append(f"  * **Status:** {status_icon}")
                lines.append("  * **Requirements:**")
                for status in f_status.requirement_statuses:
                    formatted_status = self._format_requirement_status(
                        status, indent="    "
                    )
                    lines.append(formatted_status)
                lines.append("")

        # 3. Help Guide Reference
        if not self.result.is_mergeable:
            lines.append("")
            lines.append("---")
            lines.append("")
            lines.append(
                "💡 **Need help?** For a detailed explanation of this report and how to resolve "
                f"failures, see the [Governance Gate Validation Guide]({self.GUIDE_URL})."
            )
            lines.append("")
            lines.append(
                "If you suspect a bug or issue with this validator script, please "
                f"[report an issue in the .github repository]({self.ISSUE_URL})."
            )

        return "\n".join(lines)

    def _format_requirement_status(
        self, status: RequirementStatus, indent: str = ""
    ) -> str:
        """Formats the status details of a single requirement with Markdown styling."""
        req = status.requirement
        team_desc = (
            f"team '{req.team.name}'"
            if req.team
            else f"team '{req.min_team.name}' or higher in the UCP governance hierarchy"
        )

        # A) The requirement description
        req_line = f"{indent}* **{req.min_approvals} approval{'s' if req.min_approvals > 1 else ''}** from {team_desc}"

        # B) Which requirements have been met
        met_str = "🟢 Yes" if status.is_satisfied else "🔴 No"
        approved_by_suffix = (
            f" - approved by: {', '.join(status.approvers)}" if status.approvers else ""
        )
        met_line = (
            f"{indent}  * **Met:** {met_str} ({status.approved_count}/{req.min_approvals} "
            f"approved{approved_by_suffix})"
        )

        # C) Which still need to be met (Pending if not satisfied, omitted if satisfied)
        if status.is_satisfied:
            return f"{req_line}\n{met_line}"

        missing = req.min_approvals - status.approved_count
        if status.assigned_count >= missing:
            hint = f"Waiting for approval from {team_desc}."
        else:
            needed = missing - status.assigned_count
            hint = f"Waiting for {needed} more reviewer(s) to be assigned from {team_desc}."
        pending_line = (
            f"{indent}  * **Pending:** Needs {missing} approval{'s' if missing > 1 else ''} "
            f"from {team_desc} ({status.assigned_count} eligible "
            f"reviewer{'s' if status.assigned_count != 1 else ''} assigned). {hint}"
        )

        return f"{req_line}\n{met_line}\n{pending_line}"
