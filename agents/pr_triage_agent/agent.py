# Copyright 2025 Google LLC
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

import json
import os
from pathlib import Path
from typing import Any

from google.adk import Agent
from pr_triage_agent.settings import GITHUB_BASE_URL
from pr_triage_agent.settings import IS_INTERACTIVE
from pr_triage_agent.settings import OWNER
from pr_triage_agent.settings import REPO
from pr_triage_agent.utils import error_response
from pr_triage_agent.utils import get_diff
from pr_triage_agent.utils import post_request
from pr_triage_agent.utils import read_file
from pr_triage_agent.utils import run_graphql_query
import requests

BASE_PROMPT_TEMPLATE = """# 1. Identity
You are a Pull Request (PR) triaging bot for the GitHub {REPO} repo with the owner {OWNER}.

# 2. Responsibilities
Your core responsibility includes:
- Add a label to the pull request.
- Check if the pull request is following the contribution guidelines.
- Add a comment to the pull request if it's not following the guidelines.

**IMPORTANT: {APPROVAL_INSTRUCTION}**

# 3. Guidelines & Rules
Here are the rules for labeling:
{repo_specific_guidelines}
- If you can't find an appropriate labels for the PR, follow the previous instruction that starts with "IMPORTANT:".

Here is the contribution guidelines:
<details>
<summary>CONTRIBUTING.md</summary>
{CONTRIBUTING_MD}
</details>
<details>
<summary>pull_request_template.md</summary>
{PULL_REQUEST_TEMPLATE_MD}
</details>

Here are the guidelines for checking if the PR is following the guidelines:
- The PR body (`pullRequest.body`) should be filled out according to
  `pull_request_template.md`. Ensure Description and Category are completed.
- The "statusCheckRollup" in the pull request details may help you to
  identify if the PR is following some of the guidelines (e.g. CLA
  compliance).

Here are the guidelines for the comment:
- **Be Polite and Helpful:** Start with a friendly tone.
- **Be Specific:** Clearly list only the sections from the contribution
  guidelines that are still missing.
- **Address the Author:** Mention the PR author by their username (e.g.,
  `@username`).
- **Provide Context:** Explain *why* the information or action is needed.
- **Identify yourself:** Include a bolded note (e.g. "Response from ADK
  Triaging Agent") in your comment to indicate this comment was added by an
  ADK Answering Agent.
- **Do not be repetitive:**
    - If you have already commented on this PR about a specific issue, do not
      comment about the *same* issue again if it has not been resolved.
    - If a previous issue you commented on has been resolved, but you detect a
      *new* issue with the PR, you SHOULD comment again to point out the new
      issue.
    - If you have already commented that the PR looks good, do not comment
      again unless a new issue is introduced in a later commit.

**Example Comment for a PR:**
> **Response from ADK Triaging Agent**
>
> Hello @[pr-author-username], thank you for creating this PR!
>
> This PR is a bug fix, could you please associate the github issue with this
> PR? If there is no existing issue, could you please create one?
>
> In addition, could you please provide logs or screenshot after the fix is
> applied?
>
> This information will help reviewers to review your PR more efficiently.
> Thanks!

# 4. Steps
When you are given PR details, here are the steps you should take:
- Analyze the provided PR details including title, body, diff, commits, and
  comments.
- Skip the PR (i.e. do not label or comment) if any of the following is true:
    - its state is 'CLOSED'
    - it is already labelled with one of the ALLOWED_LABELS: {ALLOWED_LABELS}.
- Check if any comment in `pullRequest.comments.nodes` is from an author
  where `comment.author.login` is different from `pullRequest.author.login`
  AND where `comment.body` does NOT contain
  "**Response from ADK Triaging Agent**".
  If such a comment exists, a human reviewer is involved, and you should skip
  commenting.
- Check if the PR is following all contribution guidelines.
  - If one or more guidelines are NOT being followed:
    - If a human reviewer is involved, do not comment.
    - Otherwise, if you have not already commented on the same unresolved
      issues, call `add_comment_to_pr` with a comment that specifies what is
      missing and points to the relevant guideline(s).
  - If ALL guidelines ARE being followed:
    - Determine the single most appropriate label from ALLOWED_LABELS:
      {ALLOWED_LABELS} and call `add_label_to_pr` to add it.
    - If no human reviewer is involved and you have NOT commented on this PR
      before, call `add_comment_to_pr` with a message like: "Hello
      @[pr-author-username], thank you for your contribution! This PR appears
      to follow our contribution guidelines. I have added the appropriate
      label(s); please wait for reviewer feedback."

# 5. Output
Present the following in an easy to read format highlighting PR number and your label.
- The PR summary in a few sentence
- The label you recommended or added with the justification
- The comment you recommended or added to the PR with the justification
"""


def get_repo_config(repo_name: str) -> tuple[str, list[str]]:
    """Loads prompt and labels for a given repo."""
    try:
        prompt_path = Path(__file__).parent / "prompts" / f"{repo_name}.txt"
        config_path = Path(__file__).parent / "configs" / f"{repo_name}.json"
        repo_specific_guidelines = read_file(prompt_path)
        with open(config_path, "r") as f:
            config = json.load(f)
        labels = config.get("allowed_labels", [])
        print(f"Loaded config for repo: {repo_name}")
        prompt = BASE_PROMPT_TEMPLATE.replace(
            "{repo_specific_guidelines}", repo_specific_guidelines
        )
        return prompt, labels
    except FileNotFoundError:
        print(f"Error: No prompt or config found for repo: {repo_name}")
        # Fallback to ucp config if no repo-specific config is found.
        print("Falling back to ucp config.")
        prompt_path = Path(__file__).parent / "prompts" / "ucp.txt"
        config_path = Path(__file__).parent / "configs" / "ucp.json"
        repo_specific_guidelines = read_file(prompt_path)
        with open(config_path, "r") as f:
            config = json.load(f)
        labels = config.get("allowed_labels", [])
        prompt = BASE_PROMPT_TEMPLATE.replace(
            "{repo_specific_guidelines}", repo_specific_guidelines
        )
        return prompt, labels


PROMPT_TEMPLATE, ALLOWED_LABELS = get_repo_config(REPO)

# FIX: Replace curly braces in
# Markdown content to prevent ADK interpolation errors.
try:
    CONTRIBUTING_MD = (
        read_file(os.environ["CONTRIBUTING_MD_PATH"])
        .replace("{", "[")
        .replace("}", "]")
    )
except (FileNotFoundError, KeyError):
    CONTRIBUTING_MD = "CONTRIBUTING.md not found."

try:
    PULL_REQUEST_TEMPLATE_MD = (
        read_file(os.environ["PULL_REQUEST_TEMPLATE_MD_PATH"])
        .replace("{", "[")
        .replace("}", "]")
    )
except (FileNotFoundError, KeyError):
    PULL_REQUEST_TEMPLATE_MD = "pull_request_template.md not found."


approval_instruction = "Do not ask for user approval for labeling or commenting!"
if IS_INTERACTIVE:
    approval_instruction = (
        "Only label or comment when the user approves the labeling or commenting!"
    )


def get_pull_request_details(pr_number: int) -> str:
    """Get the details of the specified pull request.

    Args:
      pr_number: number of the GitHub pull request.

    Returns:
      The status of this request, with the details when successful.
    """
    print(f"Fetching details for PR #{pr_number} from {OWNER}/{REPO}")
    query = """
    query($owner: String!, $repo: String!, $prNumber: Int!) {
      repository(owner: $owner, name: $repo) {
        pullRequest(number: $prNumber) {
          id
          number
          title
          body
          state
          author {
            login
          }
          labels(last: 10) {
            nodes {
              name
            }
          }
          files(last: 50) {
            nodes {
              path
            }
          }
          comments(last: 50) {
            nodes {
              id
              body
              createdAt
              author {
                login
              }
            }
          }
          commits(last: 50) {
            nodes {
              commit {
                url
                message
              }
            }
          }
          statusCheckRollup {
            state
            contexts(last: 20) {
              nodes {
                ... on StatusContext {
                  context
                  state
                  targetUrl
                }
                ... on CheckRun {
                  name
                  status
                  conclusion
                  detailsUrl
                }
              }
            }
          }
        }
      }
    }
  """
    variables = {"owner": OWNER, "repo": REPO, "prNumber": pr_number}
    url = f"{GITHUB_BASE_URL}/repos/{OWNER}/{REPO}/pulls/{pr_number}"

    try:
        response = run_graphql_query(query, variables)
        if "errors" in response:
            return error_response(str(response["errors"]))

        pr = response.get("data", {}).get("repository", {}).get("pullRequest")
        if not pr:
            return error_response(f"Pull Request #{pr_number} not found.")

        # Filter out main merge commits.
        original_commits = pr.get("commits", {}).get("nodes", {})
        if original_commits:
            filtered_commits = [
                commit_node
                for commit_node in original_commits
                if not commit_node["commit"]["message"].startswith(
                    "Merge branch 'main' into"
                )
            ]
            pr["commits"]["nodes"] = filtered_commits

        # Get diff of the PR and truncate it to avoid exceeding the maximum tokens.
        pr["diff"] = get_diff(url)[:10000]

        return {"status": "success", "pull_request": pr}
    except requests.exceptions.RequestException as e:
        return error_response(str(e))


def add_label_to_pr(pr_number: int, label: str) -> dict[str, Any]:
    """Adds a specified label on a pull request.

    Args:
        pr_number: the number of the GitHub pull request
        label: the label to add

    Returns:
        The the status of this request, with the applied label and response when
        successful.
    """
    print(f"Attempting to add label '{label}' to PR #{pr_number}")
    if label not in ALLOWED_LABELS:
        return error_response(
            f"Error: Label '{label}' is not an allowed label. Will not apply."
        )

    # Pull Request is a special issue in GitHub, so we can use issue url for PR.
    label_url = f"{GITHUB_BASE_URL}/repos/{OWNER}/{REPO}/issues/{pr_number}/labels"
    label_payload = [label]

    try:
        response = post_request(label_url, label_payload)
    except requests.exceptions.RequestException as e:
        return error_response(f"Error: {e}")

    return {
        "status": "success",
        "applied_label": label,
        "response": response,
    }


def add_comment_to_pr(pr_number: int, comment: str) -> dict[str, Any]:
    """Add the specified comment to the given PR number.

    Args:
      pr_number: the number of the GitHub pull request
      comment: the comment to add

    Returns:
      The the status of this request, with the applied comment when successful.
    """
    print(f"Attempting to add comment '{comment}' to issue #{pr_number}")

    # Pull Request is a special issue in GitHub, so we can use issue url for PR.
    url = f"{GITHUB_BASE_URL}/repos/{OWNER}/{REPO}/issues/{pr_number}/comments"
    payload = {"body": comment}

    try:
        post_request(url, payload)
    except requests.exceptions.RequestException as e:
        return error_response(f"Error: {e}")
    return {
        "status": "success",
        "added_comment": comment,
    }


root_agent = Agent(
    model="gemini-2.5-pro",
    name="ucp_pr_triaging_assistant",
    description="Triage UCP pull requests.",
    instruction=PROMPT_TEMPLATE.format(
        REPO=REPO,
        OWNER=OWNER,
        APPROVAL_INSTRUCTION=approval_instruction,
        CONTRIBUTING_MD=CONTRIBUTING_MD,
        PULL_REQUEST_TEMPLATE_MD=PULL_REQUEST_TEMPLATE_MD,
        ALLOWED_LABELS=ALLOWED_LABELS,
    ),
    tools=[
        add_label_to_pr,
        add_comment_to_pr,
    ],
)
