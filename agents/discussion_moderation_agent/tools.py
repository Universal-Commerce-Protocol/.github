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

import requests
from typing import Any
from discussion_moderation_agent.settings import OWNER, REPO, GITHUB_BASE_URL
from discussion_moderation_agent.utils import run_graphql_query, error_response, headers

def get_discussion_and_comments(discussion_number: int) -> dict[str, Any]:
    """Fetches a discussion's title, body, and comments.

    Args:
        discussion_number: The number of the GitHub discussion.

    Returns:
        A dictionary containing discussion details or an error message.
    """
    print(f"Fetching details for Discussion #{discussion_number} from {OWNER}/{REPO}")
    query = """
    query($owner: String!, $repo: String!, $discussionNumber: Int!) {
      repository(owner: $owner, name: $repo) {
        discussion(number: $discussionNumber) {
          id
          title
          body
          createdAt
          updatedAt
          category {
            name
            isAnswerable
          }
          answer {
            id
            createdAt
          }
          author {
            login
          }
          comments(last: 100) {
            nodes {
              author {
                login
              }
              body
              createdAt
            }
          }
          labels(last: 10) {
            nodes {
              name
            }
          }
        }
      }
    }
    """
    variables = {"owner": OWNER, "repo": REPO, "discussionNumber": discussion_number}

    try:
        response = run_graphql_query(query, variables)
        if "errors" in response:
            return error_response(str(response["errors"]))

        discussion = response.get("data", {}).get("repository", {}).get("discussion")
        if not discussion:
            return error_response(f"Discussion #{discussion_number} not found.")

        return {"status": "success", "discussion": discussion}
    except Exception as e:
        return error_response(str(e))

def add_label_to_discussion(discussion_id: str, label_name: str) -> dict[str, Any]:
    """Adds a label to a discussion.

    Note: This requires fetching the Label ID first if using GraphQL mutations,
    so we'll use the REST API via the repository's issues endpoint as discussions
    share labels with issues.

    Args:
        discussion_id: The GraphQL ID of the discussion (not used in REST but kept for agent signature).
        label_name: The name of the label to add (e.g., 'needs-review').

    Returns:
        A success or error status.
    """
    # We need the discussion NUMBER to use REST. Since the agent might only have the ID,
    # we'll assume the context provides enough or we use a mutation.
    # Actually, let's use the REST API with OWNER/REPO/DISCUSSION_NUMBER if available,
    # or a GraphQL mutation if we have the ID.

    print(f"Attempting to add label '{label_name}' to Discussion {discussion_id}")

    # GitHub Discussions labels can be managed via the 'addLabelsToLabelable' mutation.
    # But first we need the label ID. To keep it simple and robust, we use REST
    # using the discussion number from environment if discussion_id isn't easily mapped.

    from discussion_moderation_agent.settings import DISCUSSION_NUMBER
    pr_or_disc_num = DISCUSSION_NUMBER # Fallback

    mutation = """
    mutation($labelableId: ID!, $labelIds: [ID!]!) {
      addLabelsToLabelable(input: {labelableId: $labelableId, labelIds: $labelIds}) {
        labelable {
          ... on Discussion {
            labels(last: 10) {
              nodes {
                name
              }
            }
          }
        }
      }
    }
    """

    # To get Label ID from Name
    label_query = """
    query($owner: String!, $repo: String!) {
      repository(owner: $owner, name: $repo) {
        labels(first: 100) {
          nodes {
            id
            name
          }
        }
      }
    }
    """
    try:
        label_resp = run_graphql_query(label_query, {"owner": OWNER, "repo": REPO})
        labels = label_resp.get("data", {}).get("repository", {}).get("labels", {}).get("nodes", [])
        label_id = next((l["id"] for l in labels if l["name"].lower() == label_name.lower()), None)

        if not label_id:
            return error_response(f"Label '{label_name}' not found in repository.")

        mutation_vars = {"labelableId": discussion_id, "labelIds": [label_id]}
        run_graphql_query(mutation, mutation_vars)
        return {"status": "success", "label": label_name}
    except Exception as e:
        return error_response(str(e))
