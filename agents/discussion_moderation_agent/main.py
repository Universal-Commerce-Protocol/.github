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

import argparse
import asyncio
import logging
import sys
import time
from typing import Union

from discussion_moderation_agent import agent
from discussion_moderation_agent.settings import DISCUSSION_NUMBER
from discussion_moderation_agent.settings import EVENT_NAME
from discussion_moderation_agent.settings import OWNER
from discussion_moderation_agent.settings import REPO
from discussion_moderation_agent.utils import call_agent_async
from discussion_moderation_agent.utils import parse_number_string
from discussion_moderation_agent.utils import run_graphql_query
from google.adk.cli.utils import logs
from google.adk.runners import InMemoryRunner
import requests

APP_NAME = "discussion_moderation_app"
USER_ID = "discussion_moderation_user"

logs.setup_adk_logger(level=logging.INFO)


async def list_all_open_discussions() -> Union[list[int], None]:
    """Fetches all open discussions using pagination.

    Returns:
        A list of discussion numbers.
    """
    print(f"Attempting to fetch all open discussions from {OWNER}/{REPO}...")
    query = """
    query($owner: String!, $repo: String!, $count: Int!, $after: String) {
      repository(owner: $owner, name: $repo) {
        discussions(
          first: $count
          after: $after
          orderBy: {field: UPDATED_AT, direction: DESC}
          states: [OPEN]
        ) {
          nodes {
            number
          }
          pageInfo {
            endCursor
            hasNextPage
          }
        }
      }
    }
    """
    all_discussion_numbers = []
    has_next_page = True
    end_cursor = None
    try:
        while has_next_page:
            variables = {
                "owner": OWNER,
                "repo": REPO,
                "count": 100,
                "after": end_cursor,
            }
            response = run_graphql_query(query, variables)

            if "errors" in response:
                print(f"Error from GitHub API: {response['errors']}", file=sys.stderr)
                return None

            discussions_data = (
                response.get("data", {}).get("repository", {}).get("discussions", {})
            )
            nodes = discussions_data.get("nodes", [])
            all_discussion_numbers.extend([d["number"] for d in nodes])

            page_info = discussions_data.get("pageInfo", {})
            has_next_page = page_info.get("hasNextPage", False)
            end_cursor = page_info.get("endCursor")

        return all_discussion_numbers
    except requests.exceptions.RequestException as e:
        print(f"Request failed: {e}", file=sys.stderr)
        return None


def process_arguments():
    """Parses command-line arguments."""
    parser = argparse.ArgumentParser(
        description="A script that moderates GitHub discussions.",
        epilog=(
            "Example usage: \n"
            "\tpython -m discussion_moderation_agent.main --recent 10\n"
            "\tpython -m discussion_moderation_agent.main --discussion_number 21\n"
        ),
        formatter_class=argparse.RawTextHelpFormatter,
    )

    group = parser.add_mutually_exclusive_group(required=True)

    group.add_argument(
        "--recent",
        type=int,
        metavar="COUNT",
        help="Moderate the N most recently updated discussion numbers.",
    )

    group.add_argument(
        "--discussion_number",
        type=str,
        metavar="NUM",
        help="Moderate a specific discussion number.",
    )

    return parser.parse_args()


async def main():
    discussion_numbers_to_process = []
    if EVENT_NAME == "discussion" and DISCUSSION_NUMBER:
        print(f"EVENT: Processing specific discussion due to '{EVENT_NAME}' event.")
        discussion_number = parse_number_string(DISCUSSION_NUMBER)
        if not discussion_number:
            print(f"Error: Invalid discussion number received: {DISCUSSION_NUMBER}.")
            return
        discussion_numbers_to_process = [discussion_number]
    elif EVENT_NAME == "workflow_dispatch" and DISCUSSION_NUMBER:
        print(f"EVENT: Processing specific discussion due to '{EVENT_NAME}' event.")
        discussion_number = parse_number_string(DISCUSSION_NUMBER)
        if not discussion_number:
            print(f"Error: Invalid discussion number received: {DISCUSSION_NUMBER}.")
            return
        discussion_numbers_to_process = [discussion_number]
    else:
        print(f"EVENT: Processing batch of discussions (event: {EVENT_NAME}).")
        fetched_numbers = await list_all_open_discussions()
        if not fetched_numbers:
            print("No discussions found matching criteria. Exiting...")
            return
        discussion_numbers_to_process = fetched_numbers

    print(f"Will try to moderate discussions: {discussion_numbers_to_process}...")

    runner = InMemoryRunner(
        agent=agent.root_agent,
        app_name=APP_NAME,
    )

    for discussion_number in discussion_numbers_to_process:
        if len(discussion_numbers_to_process) > 1:
            print("#" * 80)
            print(f"Starting to process discussion #{discussion_number}...")
        # Create a new session for each discussion to avoid interference.
        session = await runner.session_service.create_session(
            app_name=APP_NAME, user_id=USER_ID
        )

        prompt = f"Please moderate GitHub discussion #{discussion_number}."

        response = await call_agent_async(runner, USER_ID, session.id, prompt)
        print(f"<<<< Agent Final Output: {response}\n")


if __name__ == "__main__":
    start_time = time.time()
    print(
        f"Start discussion moderation on {OWNER}/{REPO} at"
        f" {time.strftime('%Y-%m-%d %H:%M:%S', time.gmtime(start_time))}"
    )
    print("-" * 80)
    asyncio.run(main())
    print("-" * 80)
    end_time = time.time()
    print(
        "Discussion moderation finished at"
        f" {time.strftime('%Y-%m-%d %H:%M:%S', time.gmtime(end_time))}",
    )
    print("Total script execution time:", f"{end_time - start_time:.2f} seconds")
