# Copyright 2026 Google LLC
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

import asyncio
import time

from google.adk.agents.run_config import RunConfig
from google.adk.runners import InMemoryRunner
from google.adk.runners import Runner
from google.genai import types
from issue_triage_agent import agent
from issue_triage_agent.agent import CATEGORIES
from issue_triage_agent.settings import EVENT_NAME
from issue_triage_agent.settings import GITHUB_BASE_URL
from issue_triage_agent.settings import ISSUE_BODY
from issue_triage_agent.settings import ISSUE_COUNT_TO_PROCESS
from issue_triage_agent.settings import ISSUE_NUMBER
from issue_triage_agent.settings import ISSUE_TITLE
from issue_triage_agent.settings import OWNER
from issue_triage_agent.settings import REPO
from issue_triage_agent.utils import get_request
from issue_triage_agent.utils import parse_number_string
import requests

APP_NAME = "issue_triage_app"
USER_ID = "issue_triage_user"


async def fetch_specific_issue_details(issue_number: int):
    """Fetches details for a single issue if it needs triaging."""
    url = f"{GITHUB_BASE_URL}/repos/{OWNER}/{REPO}/issues/{issue_number}"
    print(f"Fetching details for specific issue: {url}")

    try:
        issue_data = get_request(url)
        labels = issue_data.get("labels", [])
        label_names = {label["name"] for label in labels}

        # Check issue state
        category_labels = set(CATEGORIES)
        existing_category_labels = label_names & category_labels
        has_category = bool(existing_category_labels)

        # Determine what actions are needed
        needs_category_label = not has_category

        if needs_category_label:
            print(
                f"Issue #{issue_number} needs triaging. "
                f"needs_category_label={needs_category_label}"
            )
            return {
                "number": issue_data["number"],
                "title": issue_data["title"],
                "body": issue_data.get("body", ""),
                "needs_category_label": needs_category_label,
            }
        else:
            print(f"Issue #{issue_number} is already fully triaged. Skipping.")
            return None
    except requests.exceptions.RequestException as e:
        print(f"Error fetching issue #{issue_number}: {e}")
        if hasattr(e, "response") and e.response is not None:
            print(f"Response content: {e.response.text}")
        return None


async def call_agent_async(
    runner: Runner, user_id: str, session_id: str, prompt: str
) -> str:
    """Call the agent asynchronously with the user's prompt."""
    content = types.Content(role="user", parts=[types.Part.from_text(text=prompt)])

    final_response_text = ""
    async for event in runner.run_async(
        user_id=user_id,
        session_id=session_id,
        new_message=content,
        run_config=RunConfig(save_input_blobs_as_artifacts=False),
    ):
        if (
            event.content
            and event.content.parts
            and hasattr(event.content.parts[0], "text")
            and event.content.parts[0].text
        ):
            print(f"** {event.author} (ADK): {event.content.parts[0].text}")
            if event.author == agent.root_agent.name:
                final_response_text += event.content.parts[0].text

    return final_response_text


async def main():
    runner = InMemoryRunner(
        agent=agent.root_agent,
        app_name=APP_NAME,
    )
    session = await runner.session_service.create_session(
        user_id=USER_ID,
        app_name=APP_NAME,
    )

    if (EVENT_NAME == "issues" or EVENT_NAME == "workflow_dispatch") and ISSUE_NUMBER:
        print(f"EVENT: Processing specific issue due to '{EVENT_NAME}' event.")
        issue_number = parse_number_string(ISSUE_NUMBER)
        if not issue_number:
            print(f"Error: Invalid issue number received: {ISSUE_NUMBER}.")
            return

        specific_issue = await fetch_specific_issue_details(issue_number)
        if specific_issue is None:
            print(
                f"No issue details found for #{issue_number} that needs triaging,"
                " or an error occurred. Skipping agent interaction."
            )
            return

        issue_title = ISSUE_TITLE or specific_issue["title"]
        issue_body = ISSUE_BODY or specific_issue["body"]
        needs_category_label = specific_issue.get("needs_category_label", True)

        prompt = (
            f"Triage GitHub issue #{issue_number}.\n\n"
            f'Title: "{issue_title}"\n'
            f'Body: "{issue_body}"\n\n'
            f"Issue state: needs_category_label={needs_category_label}"
        )
    else:
        print(f"EVENT: Processing batch of issues (event: {EVENT_NAME}).")
        issue_count = parse_number_string(ISSUE_COUNT_TO_PROCESS, default_value=3)
        prompt = (
            f"Please use 'list_untriaged_issues' to find {issue_count} issues that"
            " need triaging, then triage each one according to your instructions."
        )

    response = await call_agent_async(runner, USER_ID, session.id, prompt)
    print(f"<<<< Agent Final Output: {response}\n")


if __name__ == "__main__":
    start_time = time.time()
    print(
        f"Start triaging {OWNER}/{REPO} issues at"
        f" {time.strftime('%Y-%m-%d %H:%M:%S', time.gmtime(start_time))}"
    )
    print("-" * 80)
    asyncio.run(main())
    print("-" * 80)
    end_time = time.time()
    print(
        "Triaging finished at"
        f" {time.strftime('%Y-%m-%d %H:%M:%S', time.gmtime(end_time))}",
    )
    print("Total script execution time:", f"{end_time - start_time:.2f} seconds")
