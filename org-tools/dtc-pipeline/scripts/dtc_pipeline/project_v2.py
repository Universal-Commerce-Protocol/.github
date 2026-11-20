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
    DEFAULT_PROJECT_TITLE,
    DEFAULT_REPO,
    PROJECT_STATUS_OPTIONS,
    PROJECT_TRACK_OPTIONS,
    PROJECT_VERTICAL_DOMAINS,
    SPOTLIGHT_POOL_FILTER,
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

    def configure_project_collaborators(
        self,
        project_id: str,
        org: str = DEFAULT_ORG,
        admin_teams: list[str] | tuple[str, ...] = (),
        writer_teams: list[str] | tuple[str, ...] = (),
    ) -> list[dict[str, str]]:
        """Grants `ADMIN`/`WRITER` roles and links organization teams to `project_id`."""
        wanted_admins = {slug.strip().lower() for slug in admin_teams if slug.strip()}
        wanted_writers = {
            slug.strip().lower() for slug in writer_teams if slug.strip()
        } - wanted_admins
        if not (wanted_admins or wanted_writers):
            return []

        org_data = self.graphql(
            """
            query($org: String!) {
              organization(login: $org) {
                teams(first: 50) {
                  nodes { id slug }
                }
              }
            }
            """,
            {"org": org},
        )
        team_ids_by_slug = {
            t["slug"].lower(): t["id"]
            for t in (
                (org_data.get("organization") or {}).get("teams", {}).get("nodes") or []
            )
            if t and t.get("slug") and t.get("id")
        }

        collaborators: list[dict[str, str]] = []
        configured: list[dict[str, str]] = []
        for slug in sorted(wanted_admins):
            tid = team_ids_by_slug.get(slug)
            if tid:
                collaborators.append({"teamId": tid, "role": "ADMIN"})
                configured.append({"slug": slug, "team_id": tid, "role": "ADMIN"})
        for slug in sorted(wanted_writers):
            tid = team_ids_by_slug.get(slug)
            if tid:
                collaborators.append({"teamId": tid, "role": "WRITER"})
                configured.append({"slug": slug, "team_id": tid, "role": "WRITER"})

        if not collaborators:
            return []

        self.graphql(
            """
            mutation($projectId: ID!, $collaborators: [ProjectV2Collaborator!]!) {
              updateProjectV2Collaborators(input: {
                projectId: $projectId,
                collaborators: $collaborators
              }) {
                collaborators { totalCount }
              }
            }
            """,
            {"projectId": project_id, "collaborators": collaborators},
        )
        for entry in configured:
            self.graphql(
                """
                mutation($projectId: ID!, $teamId: ID!) {
                  linkProjectV2ToTeam(input: {
                    projectId: $projectId,
                    teamId: $teamId
                  }) {
                    team { id }
                  }
                }
                """,
                {"projectId": project_id, "teamId": entry["team_id"]},
            )
        return configured

    def create_dtc_project(
        self,
        owner_login: str,
        title: str = DEFAULT_PROJECT_TITLE,
        public: bool = False,
        template_project_id: str | None = None,
        admin_teams: list[str] | tuple[str, ...] = (),
        writer_teams: list[str] | tuple[str, ...] = (),
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
        if admin_teams or writer_teams:
            self.configure_project_collaborators(
                project_id,
                org=owner_login,
                admin_teams=admin_teams,
                writer_teams=writer_teams,
            )
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
        elif "View 1" in views_by_name:
            vid = views_by_name.pop("View 1")["id"]
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
                "filter": domain_filter,
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
            mutation($viewId: ID!, $name: String!, $filter: String!, $visibleFieldIds: [ID!]!) {
              updateProjectV2View(input: {
                viewId: $viewId,
                name: $name,
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
                "name": "Community Spotlight Pool",
                "filter": SPOTLIGHT_POOL_FILTER,
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

    def apply_spotlight_scan(
        self,
        scan_result: dict,
        project_ids: list[str] | None = None,
        apply: bool = False,
    ) -> dict[str, list[dict]]:
        """Syncs eligible Community Spotlight candidates (`Track` & `Priority Score`) to Project v2 without applying repo labels."""
        synced_projects: list[dict] = []

        for pid in project_ids or []:
            fields: dict[str, str] = {}
            options: dict[str, dict[str, str]] = {}
            existing_items: dict[int, dict] = {}
            cursor: str | None = None
            while True:
                proj_data = self.graphql(
                    """
                    query($projectId: ID!, $cursor: String) {
                      node(id: $projectId) {
                        ... on ProjectV2 {
                          fields(first: 30) {
                            nodes {
                              ... on ProjectV2FieldCommon { id name }
                              ... on ProjectV2SingleSelectField {
                                id
                                name
                                options { id name }
                              }
                            }
                          }
                          items(first: 100, after: $cursor) {
                            pageInfo { hasNextPage endCursor }
                            nodes {
                              id
                              content {
                                ... on Issue { id number }
                                ... on PullRequest { id number }
                              }
                              statusVal: fieldValueByName(name: "Status") {
                                ... on ProjectV2ItemFieldSingleSelectValue { name }
                              }
                              trackVal: fieldValueByName(name: "Track") {
                                ... on ProjectV2ItemFieldSingleSelectValue { name }
                              }
                              scoreVal: fieldValueByName(name: "Priority Score") {
                                ... on ProjectV2ItemFieldNumberValue { number }
                              }
                            }
                          }
                        }
                      }
                    }
                    """,
                    {"projectId": pid, "cursor": cursor},
                )
                pnode = proj_data.get("node") or {}
                if not fields:
                    for f in pnode.get("fields", {}).get("nodes") or []:
                        if not f or "name" not in f:
                            continue
                        fields[f["name"]] = f["id"]
                        if "options" in f:
                            options[f["name"]] = {
                                o["name"]: o["id"] for o in f["options"]
                            }
                items_conn = pnode.get("items") or {}
                for inode in items_conn.get("nodes") or []:
                    c = (inode or {}).get("content") or {}
                    if c.get("number") is not None:
                        existing_items[c["number"]] = inode
                page_info = items_conn.get("pageInfo") or {}
                if not page_info.get("hasNextPage"):
                    break
                cursor = page_info.get("endCursor")

            for cand, _geval, score in scan_result.get("eligible") or []:
                if not cand.node_id:
                    continue
                inode = existing_items.get(cand.number)
                item_id = inode["id"] if inode else None
                curr_status = ((inode or {}).get("statusVal") or {}).get("name")
                curr_track = ((inode or {}).get("trackVal") or {}).get("name")
                curr_score = ((inode or {}).get("scoreVal") or {}).get("number")
                cand_labels_lower = {lbl.lower() for lbl in cand.labels}
                target_track = (
                    "General Track"
                    if curr_track == "General Track"
                    or "gov:tc-meeting" in cand_labels_lower
                    else "Community Spotlight"
                )

                if apply:
                    if not item_id:
                        add_res = self.graphql(
                            """
                            mutation($projectId: ID!, $contentId: ID!) {
                              addProjectV2ItemById(input: {projectId: $projectId, contentId: $contentId}) {
                                item { id }
                              }
                            }
                            """,
                            {"projectId": pid, "contentId": cand.node_id},
                        )
                        item_id = add_res["addProjectV2ItemById"]["item"]["id"]

                    if not curr_status and "Status" in fields:
                        self.graphql(
                            """
                            mutation($projectId: ID!, $itemId: ID!, $fieldId: ID!, $optId: String!) {
                              updateProjectV2ItemFieldValue(input: {
                                projectId: $projectId,
                                itemId: $itemId,
                                fieldId: $fieldId,
                                value: { singleSelectOptionId: $optId }
                              }) {
                                projectV2Item { id }
                              }
                            }
                            """,
                            {
                                "projectId": pid,
                                "itemId": item_id,
                                "fieldId": fields["Status"],
                                "optId": options["Status"]["Triage / Unscheduled"],
                            },
                        )

                    if (
                        curr_track != target_track
                        and "Track" in fields
                        and target_track in options.get("Track", {})
                    ):
                        self.graphql(
                            """
                            mutation($projectId: ID!, $itemId: ID!, $fieldId: ID!, $optId: String!) {
                              updateProjectV2ItemFieldValue(input: {
                                projectId: $projectId,
                                itemId: $itemId,
                                fieldId: $fieldId,
                                value: { singleSelectOptionId: $optId }
                              }) {
                                projectV2Item { id }
                              }
                            }
                            """,
                            {
                                "projectId": pid,
                                "itemId": item_id,
                                "fieldId": fields["Track"],
                                "optId": options["Track"][target_track],
                            },
                        )

                    if curr_score != float(score.total) and "Priority Score" in fields:
                        self.graphql(
                            """
                            mutation($projectId: ID!, $itemId: ID!, $fieldId: ID!, $num: Float!) {
                              updateProjectV2ItemFieldValue(input: {
                                projectId: $projectId,
                                itemId: $itemId,
                                fieldId: $fieldId,
                                value: { number: $num }
                              }) {
                                projectV2Item { id }
                              }
                            }
                            """,
                            {
                                "projectId": pid,
                                "itemId": item_id,
                                "fieldId": fields["Priority Score"],
                                "num": float(score.total),
                            },
                        )

                synced_projects.append(
                    {
                        "project_id": pid,
                        "number": cand.number,
                        "score": score.total,
                        "applied": apply,
                    }
                )

        return {"synced_projects": synced_projects}

    @staticmethod
    def _resolve_status_mover(
        project_id: str,
        content: dict,
        status_value: dict,
        target_status: str = "Next DTC Agenda",
    ) -> dict:
        """Resolves the user who moved an item to `target_status`, preferring `ProjectV2ItemStatusChangedEvent`."""
        events = ((content.get("timelineItems") or {}).get("nodes")) or []
        for ev in reversed(events):
            if not ev or ev.get("status") != target_status or ev.get("wasAutomated"):
                continue
            ev_proj = ev.get("project") or {}
            if ev_proj.get("id") and ev_proj["id"] != project_id:
                continue
            actor = ev.get("actor") or {}
            if actor.get("login") and actor.get("id"):
                return actor
        return status_value.get("creator") or {}

    def sync_agenda_assignees(
        self,
        project_id: str,
        apply: bool = False,
    ) -> dict[str, list[dict]]:
        """Auto-assigns TC movers on `Next DTC Agenda` and stamps `General Track` on `gov:tc-meeting` items."""
        items: list[dict] = []
        track_field_id: str | None = None
        general_track_opt_id: str | None = None
        cursor: str | None = None
        while True:
            data = self.graphql(
                """
                query($projectId: ID!, $cursor: String) {
                  node(id: $projectId) {
                    ... on ProjectV2 {
                      fields(first: 30) {
                        nodes {
                          ... on ProjectV2SingleSelectField {
                            id
                            name
                            options { id name }
                          }
                        }
                      }
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
                              state
                              labels(first: 20) { nodes { name } }
                              assignees(first: 20) { nodes { login } }
                              timelineItems(last: 10, itemTypes: [PROJECT_V2_ITEM_STATUS_CHANGED_EVENT]) {
                                nodes {
                                  ... on ProjectV2ItemStatusChangedEvent {
                                    status
                                    wasAutomated
                                    project { id }
                                    actor {
                                      __typename
                                      login
                                      ... on User { id login }
                                    }
                                  }
                                }
                              }
                            }
                            ... on PullRequest {
                              id
                              number
                              title
                              state
                              labels(first: 20) { nodes { name } }
                              assignees(first: 20) { nodes { login } }
                              timelineItems(last: 10, itemTypes: [PROJECT_V2_ITEM_STATUS_CHANGED_EVENT]) {
                                nodes {
                                  ... on ProjectV2ItemStatusChangedEvent {
                                    status
                                    wasAutomated
                                    project { id }
                                    actor {
                                      __typename
                                      login
                                      ... on User { id login }
                                    }
                                  }
                                }
                              }
                            }
                          }
                          trackValue: fieldValueByName(name: "Track") {
                            ... on ProjectV2ItemFieldSingleSelectValue { name }
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
            pnode = data.get("node") or {}
            if track_field_id is None:
                for fnode in (pnode.get("fields") or {}).get("nodes") or []:
                    if fnode and fnode.get("name") == "Track":
                        track_field_id = fnode.get("id")
                        for opt in fnode.get("options") or []:
                            if opt and opt.get("name") == "General Track":
                                general_track_opt_id = opt.get("id")
            conn = pnode.get("items") or {}
            for node in conn.get("nodes") or []:
                if node:
                    items.append(node)
            page_info = conn.get("pageInfo") or {}
            if not page_info.get("hasNextPage"):
                break
            cursor = page_info.get("endCursor")

        assigned: list[dict] = []
        already_assigned: list[dict] = []
        synced_tracks: list[dict] = []
        for item in items:
            content = item.get("content") or {}
            content_id = content.get("id")
            number = content.get("number")
            if not content_id or number is None:
                continue

            item_labels = {
                (lbl.get("name") or "").strip().lower()
                for lbl in ((content.get("labels") or {}).get("nodes") or [])
                if lbl and lbl.get("name")
            }
            curr_track = ((item.get("trackValue") or {}).get("name") or "").strip()
            item_state = (content.get("state") or "OPEN").upper()
            if (
                not curr_track
                and item_state == "OPEN"
                and "gov:tc-meeting" in item_labels
                and track_field_id
                and general_track_opt_id
            ):
                if apply:
                    self.graphql(
                        """
                        mutation($projectId: ID!, $itemId: ID!, $fieldId: ID!, $optId: String!) {
                          updateProjectV2ItemFieldValue(input: {
                            projectId: $projectId,
                            itemId: $itemId,
                            fieldId: $fieldId,
                            value: { singleSelectOptionId: $optId }
                          }) {
                            projectV2Item { id }
                          }
                        }
                        """,
                        {
                            "projectId": project_id,
                            "itemId": item["id"],
                            "fieldId": track_field_id,
                            "optId": general_track_opt_id,
                        },
                    )
                synced_tracks.append(
                    {
                        "number": number,
                        "title": content.get("title") or "",
                        "track": "General Track",
                        "applied": apply,
                    }
                )

            sv = item.get("statusValue") or {}
            if sv.get("name") != "Next DTC Agenda":
                continue
            creator = self._resolve_status_mover(project_id, content, sv)
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
            "synced_tracks": synced_tracks,
        }

    def sync_milestoned_items(
        self,
        project_id: str,
        org: str = DEFAULT_ORG,
        repo: str = DEFAULT_REPO,
        apply: bool = False,
    ) -> dict[str, list[dict]]:
        """Adds open Issues and Pull Requests assigned to any milestone in `org/repo` onto `project_id`."""
        milestoned_nodes: list[dict] = []
        search_cursor: str | None = None
        search_query = f"repo:{org}/{repo} is:open milestone:*"
        while True:
            search_data = self.graphql(
                """
                query($query: String!, $cursor: String) {
                  search(query: $query, type: ISSUE, first: 100, after: $cursor) {
                    pageInfo { hasNextPage endCursor }
                    nodes {
                      ... on Issue {
                        id
                        number
                        title
                        milestone { title }
                      }
                      ... on PullRequest {
                        id
                        number
                        title
                        milestone { title }
                      }
                    }
                  }
                }
                """,
                {"query": search_query, "cursor": search_cursor},
            )
            conn = search_data.get("search") or {}
            for node in conn.get("nodes") or []:
                if node and node.get("id") and node.get("number") is not None:
                    milestoned_nodes.append(node)
            page_info = conn.get("pageInfo") or {}
            if not page_info.get("hasNextPage"):
                break
            search_cursor = page_info.get("endCursor")

        fields: dict[str, str] = {}
        options: dict[str, dict[str, str]] = {}
        existing_by_id: dict[str, dict] = {}
        existing_by_num: dict[int, dict] = {}
        proj_cursor: str | None = None
        while True:
            proj_data = self.graphql(
                """
                query($projectId: ID!, $cursor: String) {
                  node(id: $projectId) {
                    ... on ProjectV2 {
                      fields(first: 30) {
                        nodes {
                          ... on ProjectV2FieldCommon { id name }
                          ... on ProjectV2SingleSelectField {
                            id
                            name
                            options { id name }
                          }
                        }
                      }
                      items(first: 100, after: $cursor) {
                        pageInfo { hasNextPage endCursor }
                        nodes {
                          id
                          isArchived
                          content {
                            ... on Issue { id number }
                            ... on PullRequest { id number }
                          }
                          statusVal: fieldValueByName(name: "Status") {
                            ... on ProjectV2ItemFieldSingleSelectValue { name }
                          }
                          trackVal: fieldValueByName(name: "Track") {
                            ... on ProjectV2ItemFieldSingleSelectValue { name }
                          }
                        }
                      }
                    }
                  }
                }
                """,
                {"projectId": project_id, "cursor": proj_cursor},
            )
            pnode = proj_data.get("node") or {}
            if not fields:
                for f in (pnode.get("fields") or {}).get("nodes") or []:
                    if not f or "name" not in f:
                        continue
                    fields[f["name"]] = f["id"]
                    if "options" in f:
                        options[f["name"]] = {o["name"]: o["id"] for o in f["options"]}
            items_conn = pnode.get("items") or {}
            for inode in items_conn.get("nodes") or []:
                if not inode:
                    continue
                c = inode.get("content") or {}
                if c.get("id"):
                    existing_by_id[c["id"]] = inode
                if c.get("number") is not None:
                    existing_by_num[c["number"]] = inode
            page_info = items_conn.get("pageInfo") or {}
            if not page_info.get("hasNextPage"):
                break
            proj_cursor = page_info.get("endCursor")

        added: list[dict] = []
        synced_tracks: list[dict] = []
        already_present: list[dict] = []
        triage_opt_id = options.get("Status", {}).get("Triage / Unscheduled")
        general_track_opt_id = options.get("Track", {}).get("General Track")

        for node in milestoned_nodes:
            content_id = node["id"]
            number = node["number"]
            title = node.get("title") or ""
            ms_title = (node.get("milestone") or {}).get("title") or ""
            existing = existing_by_id.get(content_id) or existing_by_num.get(number)
            if existing:
                already_present.append(
                    {
                        "number": number,
                        "title": title,
                        "milestone": ms_title,
                        "archived": bool(existing.get("isArchived")),
                    }
                )
                curr_track = (
                    (existing.get("trackVal") or {}).get("name") or ""
                ).strip()
                if (
                    not existing.get("isArchived")
                    and not curr_track
                    and "Track" in fields
                    and general_track_opt_id
                ):
                    if apply:
                        self.graphql(
                            """
                            mutation($projectId: ID!, $itemId: ID!, $fieldId: ID!, $optId: String!) {
                              updateProjectV2ItemFieldValue(input: {
                                projectId: $projectId,
                                itemId: $itemId,
                                fieldId: $fieldId,
                                value: { singleSelectOptionId: $optId }
                              }) {
                                projectV2Item { id }
                              }
                            }
                            """,
                            {
                                "projectId": project_id,
                                "itemId": existing["id"],
                                "fieldId": fields["Track"],
                                "optId": general_track_opt_id,
                            },
                        )
                    synced_tracks.append(
                        {
                            "number": number,
                            "title": title,
                            "track": "General Track",
                            "applied": apply,
                        }
                    )
                continue

            if apply:
                add_res = self.graphql(
                    """
                    mutation($projectId: ID!, $contentId: ID!) {
                      addProjectV2ItemById(input: {projectId: $projectId, contentId: $contentId}) {
                        item { id }
                      }
                    }
                    """,
                    {"projectId": project_id, "contentId": content_id},
                )
                item_id = add_res["addProjectV2ItemById"]["item"]["id"]
                if "Status" in fields and triage_opt_id:
                    self.graphql(
                        """
                        mutation($projectId: ID!, $itemId: ID!, $fieldId: ID!, $optId: String!) {
                          updateProjectV2ItemFieldValue(input: {
                            projectId: $projectId,
                            itemId: $itemId,
                            fieldId: $fieldId,
                            value: { singleSelectOptionId: $optId }
                          }) {
                            projectV2Item { id }
                          }
                        }
                        """,
                        {
                            "projectId": project_id,
                            "itemId": item_id,
                            "fieldId": fields["Status"],
                            "optId": triage_opt_id,
                        },
                    )
                if "Track" in fields and general_track_opt_id:
                    self.graphql(
                        """
                        mutation($projectId: ID!, $itemId: ID!, $fieldId: ID!, $optId: String!) {
                          updateProjectV2ItemFieldValue(input: {
                            projectId: $projectId,
                            itemId: $itemId,
                            fieldId: $fieldId,
                            value: { singleSelectOptionId: $optId }
                          }) {
                            projectV2Item { id }
                          }
                        }
                        """,
                        {
                            "projectId": project_id,
                            "itemId": item_id,
                            "fieldId": fields["Track"],
                            "optId": general_track_opt_id,
                        },
                    )
            added.append(
                {
                    "number": number,
                    "title": title,
                    "milestone": ms_title,
                    "applied": apply,
                }
            )

        return {
            "added": added,
            "synced_tracks": synced_tracks,
            "already_present": already_present,
        }
