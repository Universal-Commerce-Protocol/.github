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

"""GitHub Projects v2 GraphQL client and 5-view layout configurator."""

from __future__ import annotations

import json
import time
import urllib.error
import urllib.request

from .config import (
    DEFAULT_MAINTAINERS_PATH,
    DEFAULT_ORG,
    DEFAULT_REPO,
    PROJECT_STATUS_OPTIONS,
    PROJECT_TRACK_OPTIONS,
    PROJECT_VERTICAL_DOMAINS,
)
from .spotlight import (
    AuthorMeta,
    fetch_excluded_handles,
    is_bot_user,
    scan_live_spotlight,
)


class GitHubProjectV2Manager:
    """Manages GitHub Projects v2 provisioning and Community Spotlight scanning via GraphQL."""

    def __init__(self, token: str, api_url: str = "https://api.github.com"):
        self.token = token
        self.graphql_url = f"{api_url.rstrip('/')}/graphql"

    def graphql(self, query: str, variables: dict | None = None) -> dict:
        """Executes a GraphQL request against GitHub's API with transient 5xx retry."""
        payload = {"query": query, "variables": variables or {}}
        for attempt in range(4):
            try:
                req = urllib.request.Request(  # noqa: S310
                    self.graphql_url,
                    data=json.dumps(payload).encode("utf-8"),
                    headers={
                        "Authorization": f"Bearer {self.token}",
                        "Accept": "application/vnd.github+json",
                        "Content-Type": "application/json",
                        "User-Agent": "ucp-dtc-pipeline",
                    },
                    method="POST",
                )
                with urllib.request.urlopen(req, timeout=30) as resp:  # noqa: S310
                    result = json.loads(resp.read().decode("utf-8"))
                if "errors" in result:
                    err_str = json.dumps(result["errors"])
                    if "Something went wrong" in err_str and attempt < 3:
                        time.sleep(1.0 * (attempt + 1))
                        continue
                    raise RuntimeError(f"GraphQL errors: {err_str}")
                return result.get("data", {})
            except urllib.error.HTTPError as exc:
                if exc.code in (429, 500, 502, 503, 504) and attempt < 3:
                    time.sleep(1.0 * (attempt + 1))
                    continue
                raise
            except urllib.error.URLError:
                if attempt < 3:
                    time.sleep(1.0 * (attempt + 1))
                    continue
                raise
        raise RuntimeError("GraphQL retries exhausted")

    def get_owner_id(self, login: str) -> str:
        """Resolves a GitHub user or organization login to its GraphQL node ID."""
        data = self.graphql(
            """
            query($login: String!) {
              repositoryOwner(login: $login) {
                id
              }
            }
            """,
            {"login": login},
        )
        owner = data.get("repositoryOwner")
        if not owner or not owner.get("id"):
            raise RuntimeError(f"Could not resolve owner ID for '{login}'.")
        return owner["id"]

    def delete_project(self, project_id: str) -> None:
        """Deletes a GitHub Project v2 board by its node ID."""
        self.graphql(
            """
            mutation($projectId: ID!) {
              deleteProjectV2(input: {projectId: $projectId}) {
                projectV2 { id }
              }
            }
            """,
            {"projectId": project_id},
        )

    @staticmethod
    def _options_match(
        existing_options: list[dict] | None,
        target_options: tuple[tuple[str, str, str], ...],
    ) -> bool:
        """Returns True if `existing_options` already match `target_options` `(name, color, description)`."""
        if not existing_options or len(existing_options) != len(target_options):
            return False
        return [
            (
                opt.get("name"),
                opt.get("color"),
                opt.get("description") or "",
            )
            for opt in existing_options
        ] == list(target_options)

    def _ensure_status_field(
        self,
        status_field_id: str,
        existing_options: list[dict] | None = None,
    ) -> dict[str, str]:
        """Configures the 6-column `Status` options (including `Next DTC Agenda`) on `status_field_id`."""
        if self._options_match(existing_options, PROJECT_STATUS_OPTIONS):
            return {
                opt["name"]: opt["id"]
                for opt in (existing_options or [])
                if opt.get("name") and opt.get("id")
            }
        res = self.graphql(
            """
            mutation($fieldId: ID!, $options: [ProjectV2SingleSelectFieldOptionInput!]!) {
              updateProjectV2Field(input: {
                fieldId: $fieldId,
                singleSelectOptions: $options
              }) {
                projectV2Field {
                  ... on ProjectV2SingleSelectField {
                    id
                    options { id name }
                  }
                }
              }
            }
            """,
            {
                "fieldId": status_field_id,
                "options": [
                    {"name": name, "color": color, "description": desc}
                    for name, color, desc in PROJECT_STATUS_OPTIONS
                ],
            },
        )
        return {
            opt["name"]: opt["id"]
            for opt in res["updateProjectV2Field"]["projectV2Field"]["options"]
        }

    def _ensure_track_and_score_fields(
        self,
        project_id: str,
        existing_fields: dict[str, str],
        existing_options_by_field: dict[str, list[dict]] | None = None,
    ) -> None:
        track_options = [
            {"name": name, "color": color, "description": desc}
            for name, color, desc in PROJECT_TRACK_OPTIONS
        ]
        if "Track" in existing_fields:
            existing_track_opts = (existing_options_by_field or {}).get("Track")
            if not self._options_match(existing_track_opts, PROJECT_TRACK_OPTIONS):
                self.graphql(
                    """
                    mutation($fieldId: ID!, $options: [ProjectV2SingleSelectFieldOptionInput!]!) {
                      updateProjectV2Field(input: {
                        fieldId: $fieldId,
                        singleSelectOptions: $options
                      }) {
                        projectV2Field {
                          ... on ProjectV2SingleSelectField { id }
                        }
                      }
                    }
                    """,
                    {"fieldId": existing_fields["Track"], "options": track_options},
                )
        else:
            self.graphql(
                """
                mutation($projectId: ID!, $options: [ProjectV2SingleSelectFieldOptionInput!]!) {
                  createProjectV2Field(input: {
                    projectId: $projectId,
                    dataType: SINGLE_SELECT,
                    name: "Track",
                    singleSelectOptions: $options
                  }) {
                    projectV2Field {
                      ... on ProjectV2SingleSelectField { id }
                    }
                  }
                }
                """,
                {"projectId": project_id, "options": track_options},
            )

        if "Priority Score" not in existing_fields:
            self.graphql(
                """
                mutation($projectId: ID!) {
                  createProjectV2Field(input: {
                    projectId: $projectId,
                    dataType: NUMBER,
                    name: "Priority Score"
                  }) {
                    projectV2Field {
                      ... on ProjectV2Field { id }
                    }
                  }
                }
                """,
                {"projectId": project_id},
            )

    def create_dtc_project(
        self,
        owner_login: str,
        title: str = "UCP DTC Review Pipeline",
        public: bool = False,
        template_project_id: str | None = None,
    ) -> dict[str, str]:
        """Creates or clones a GitHub Project v2 board and configures UCP DTC fields and 5 views."""
        owner_id = self.get_owner_id(owner_login)
        if template_project_id:
            create_res = self.graphql(
                """
                mutation($projectId: ID!, $ownerId: ID!, $title: String!) {
                  copyProjectV2(input: {
                    projectId: $projectId,
                    ownerId: $ownerId,
                    title: $title,
                    includeDraftIssues: false
                  }) {
                    projectV2 { id number url title }
                  }
                }
                """,
                {
                    "projectId": template_project_id,
                    "ownerId": owner_id,
                    "title": title,
                },
            )
            project = create_res["copyProjectV2"]["projectV2"]
        else:
            create_res = self.graphql(
                """
                mutation($ownerId: ID!, $title: String!) {
                  createProjectV2(input: {ownerId: $ownerId, title: $title}) {
                    projectV2 { id number url title }
                  }
                }
                """,
                {"ownerId": owner_id, "title": title},
            )
            project = create_res["createProjectV2"]["projectV2"]
        project_id = project["id"]

        self.graphql(
            """
            mutation($projectId: ID!, $public: Boolean!, $shortDescription: String!) {
              updateProjectV2(input: {
                projectId: $projectId,
                public: $public,
                shortDescription: $shortDescription
              }) {
                projectV2 { id }
              }
            }
            """,
            {
                "projectId": project_id,
                "public": public,
                "shortDescription": (
                    "Unified DTC agenda review queue and Community Spotlight pipeline "
                    "(Shopping, Payments, Food, Lodging)."
                ),
            },
        )

        fields_data = self.graphql(
            """
            query($projectId: ID!) {
              node(id: $projectId) {
                ... on ProjectV2 {
                  fields(first: 40) {
                    nodes {
                      ... on ProjectV2FieldCommon { id name }
                      ... on ProjectV2SingleSelectField {
                        id
                        name
                        options { id name color description }
                      }
                    }
                  }
                }
              }
            }
            """,
            {"projectId": project_id},
        )
        field_nodes = [
            node
            for node in (
                fields_data.get("node", {}).get("fields", {}).get("nodes") or []
            )
            if node and node.get("name") and node.get("id")
        ]
        existing_fields = {node["name"]: node["id"] for node in field_nodes}
        existing_options_by_field = {
            node["name"]: node["options"]
            for node in field_nodes
            if isinstance(node.get("options"), list)
        }

        if "Status" in existing_fields:
            self._ensure_status_field(
                existing_fields["Status"],
                existing_options=existing_options_by_field.get("Status"),
            )
        self._ensure_track_and_score_fields(
            project_id,
            existing_fields,
            existing_options_by_field=existing_options_by_field,
        )
        self.configure_project_views(project_id)
        return project

    def _upsert_board_view(
        self,
        project_id: str,
        view_name: str,
        domain_filter: str,
        visible_fields: list[str],
        views_by_name: dict[str, dict],
    ) -> dict:
        if view_name in views_by_name:
            vid = views_by_name[view_name]["id"]
            target_filter = views_by_name[view_name].get("filter") or domain_filter
        else:
            vid = self.graphql(
                """
                mutation($projectId: ID!, $name: String!, $visibleFieldIds: [ID!]!) {
                  createProjectV2View(input: {
                    projectId: $projectId,
                    name: $name,
                    layout: BOARD_LAYOUT,
                    configuration: { visibleFieldIds: $visibleFieldIds }
                  }) {
                    projectV2View { id number name }
                  }
                }
                """,
                {
                    "projectId": project_id,
                    "name": view_name,
                    "visibleFieldIds": visible_fields,
                },
            )["createProjectV2View"]["projectV2View"]["id"]
            target_filter = domain_filter

        return self.graphql(
            """
            mutation($viewId: ID!, $name: String!, $filter: String!, $visibleFieldIds: [ID!]!) {
              updateProjectV2View(input: {
                viewId: $viewId,
                name: $name,
                layout: BOARD_LAYOUT,
                filter: $filter,
                configuration: { visibleFieldIds: $visibleFieldIds }
              }) {
                projectV2View { id number name layout filter }
              }
            }
            """,
            {
                "viewId": vid,
                "name": view_name,
                "filter": target_filter,
                "visibleFieldIds": visible_fields,
            },
        )["updateProjectV2View"]["projectV2View"]

    def _upsert_spotlight_pool_view(
        self,
        project_id: str,
        fields: dict[str, str],
        views_by_name: dict[str, dict],
    ) -> dict:
        spotlight_fields = [
            fields[n]
            for n in (
                "Title",
                "Priority Score",
                "Status",
                "Milestone",
                "Assignees",
                "Linked pull requests",
            )
            if n in fields
        ]
        if "Community Spotlight Pool" in views_by_name:
            cs_id = views_by_name["Community Spotlight Pool"]["id"]
        else:
            cs_id = self.graphql(
                """
                mutation($projectId: ID!, $visibleFieldIds: [ID!]!) {
                  createProjectV2View(input: {
                    projectId: $projectId,
                    name: "Community Spotlight Pool",
                    layout: TABLE_LAYOUT,
                    configuration: { visibleFieldIds: $visibleFieldIds }
                  }) {
                    projectV2View { id }
                  }
                }
                """,
                {"projectId": project_id, "visibleFieldIds": spotlight_fields},
            )["createProjectV2View"]["projectV2View"]["id"]
        return self.graphql(
            """
            mutation($viewId: ID!, $filter: String!, $visibleFieldIds: [ID!]!) {
              updateProjectV2View(input: {
                viewId: $viewId,
                layout: TABLE_LAYOUT,
                filter: $filter,
                configuration: { visibleFieldIds: $visibleFieldIds }
              }) {
                projectV2View { id number name layout filter }
              }
            }
            """,
            {
                "viewId": cs_id,
                "filter": (
                    views_by_name.get("Community Spotlight Pool", {}).get("filter")
                    or "label:community-spotlight"
                ),
                "visibleFieldIds": spotlight_fields,
            },
        )["updateProjectV2View"]["projectV2View"]

    def configure_project_views(self, project_id: str) -> list[dict]:
        """Configures the 4 vertical TC Boards (`<Vertical> TC`) and the `Community Spotlight Pool` Table."""
        proj_data = self.graphql(
            """
            query($projectId: ID!) {
              node(id: $projectId) {
                ... on ProjectV2 {
                  fields(first: 40) {
                    nodes {
                      ... on ProjectV2FieldCommon { id name }
                    }
                  }
                  views(first: 20) {
                    nodes { id number name layout filter }
                  }
                }
              }
            }
            """,
            {"projectId": project_id},
        )
        pnode = proj_data.get("node") or {}
        fields = {
            f["name"]: f["id"]
            for f in (pnode.get("fields", {}).get("nodes") or [])
            if f and f.get("name") and f.get("id")
        }
        views_by_name = {
            v["name"]: v
            for v in (pnode.get("views", {}).get("nodes") or [])
            if v and v.get("name") and v.get("id")
        }

        tc_fields = [
            fields[n]
            for n in (
                "Title",
                "Status",
                "Milestone",
                "Track",
                "Priority Score",
                "Assignees",
                "Linked pull requests",
            )
            if n in fields
        ]
        configured: list[dict] = []
        for vertical, domain_filter in PROJECT_VERTICAL_DOMAINS:
            configured.append(
                self._upsert_board_view(
                    project_id,
                    f"{vertical} TC",
                    domain_filter,
                    tc_fields,
                    views_by_name,
                )
            )

        configured.append(
            self._upsert_spotlight_pool_view(project_id, fields, views_by_name)
        )
        return configured

    def fetch_excluded_handles(self, org: str = DEFAULT_ORG) -> set[str]:
        """Fetches GitHub handles belonging to UCP governance/maintainer teams."""
        return fetch_excluded_handles(self.graphql, org=org)

    def scan_live_spotlight(
        self,
        org: str = DEFAULT_ORG,
        repo: str = DEFAULT_REPO,
        maintainers_path: str = DEFAULT_MAINTAINERS_PATH,
    ) -> dict:
        """Runs a strictly read-only live Community Spotlight scan against `org/repo`."""
        return scan_live_spotlight(
            self.graphql,
            org=org,
            repo=repo,
            maintainers_path=maintainers_path,
        )

    def sync_agenda_assignees(
        self,
        project_id: str,
        apply: bool = False,
    ) -> dict[str, list[dict]]:
        """Auto-assigns the TC member who dragged an item into `Next DTC Agenda` via `statusValue.creator`."""
        items: list[dict] = []
        cursor: str | None = None
        while True:
            data = self.graphql(
                """
                query($projectId: ID!, $cursor: String) {
                  node(id: $projectId) {
                    ... on ProjectV2 {
                      items(first: 100, after: $cursor) {
                        pageInfo { hasNextPage endCursor }
                        nodes {
                          id
                          content {
                            __typename
                            ... on Issue {
                              id
                              number
                              title
                              assignees(first: 20) { nodes { login } }
                            }
                            ... on PullRequest {
                              id
                              number
                              title
                              assignees(first: 20) { nodes { login } }
                            }
                          }
                          statusValue: fieldValueByName(name: "Status") {
                            ... on ProjectV2ItemFieldSingleSelectValue {
                              name
                              updatedAt
                              creator {
                                __typename
                                login
                                ... on User { id login }
                              }
                            }
                          }
                        }
                      }
                    }
                  }
                }
                """,
                {"projectId": project_id, "cursor": cursor},
            )
            conn = (data.get("node") or {}).get("items") or {}
            for node in conn.get("nodes") or []:
                if node:
                    items.append(node)
            page_info = conn.get("pageInfo") or {}
            if not page_info.get("hasNextPage"):
                break
            cursor = page_info.get("endCursor")

        assigned: list[dict] = []
        already_assigned: list[dict] = []
        for item in items:
            sv = item.get("statusValue") or {}
            if sv.get("name") != "Next DTC Agenda":
                continue
            content = item.get("content") or {}
            content_id = content.get("id")
            number = content.get("number")
            if not content_id or number is None:
                continue
            creator = sv.get("creator") or {}
            creator_login = (creator.get("login") or "").strip()
            creator_id = creator.get("id")
            creator_type = creator.get("__typename") or "User"
            if not creator_login or not creator_id:
                continue
            if is_bot_user(AuthorMeta(login=creator_login, user_type=creator_type)):
                continue

            current_assignees = {
                (a.get("login") or "").strip().lower()
                for a in ((content.get("assignees") or {}).get("nodes") or [])
                if a and a.get("login")
            }
            entry = {
                "number": number,
                "title": content.get("title") or "",
                "assignee": creator_login,
                "applied": apply,
            }
            if creator_login.lower() in current_assignees:
                already_assigned.append(entry)
                continue

            if apply:
                self.graphql(
                    """
                    mutation($assignableId: ID!, $assigneeIds: [ID!]!) {
                      addAssigneesToAssignable(input: {
                        assignableId: $assignableId,
                        assigneeIds: $assigneeIds
                      }) {
                        assignable { __typename }
                      }
                    }
                    """,
                    {
                        "assignableId": content_id,
                        "assigneeIds": [creator_id],
                    },
                )
            assigned.append(entry)

        return {
            "assigned": assigned,
            "already_assigned": already_assigned,
        }
