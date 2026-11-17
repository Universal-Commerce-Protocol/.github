# DTC Review Pipeline & Community Spotlight Engine

Implements the governance workflow for surfacing and resolving Issues and Pull Requests in weekly Domain Technical Council meetings across `Universal-Commerce-Protocol/ucp`.

## Project Board Architecture (`DTC Review Pipeline`)

The pipeline manages a single public organization-level GitHub Project v2 board (**`DTC Review Pipeline`**) with 5 views, 6 `Status` columns, and 2 custom fields (`Track` and `Priority Score`).

### Views

| View                           | Layout           | Filter                            | Sort / Column Limit                                  |
| :----------------------------- | :--------------- | :-------------------------------- | :--------------------------------------------------- |
| **`Shopping TC`**              | Board (`Status`) | `label:area:shopping,area:common` | Created (newest first); `Next DTC Agenda` limit: `7` |
| **`Payments TC`**              | Board (`Status`) | `label:area:payments`             | Created (newest first); `Next DTC Agenda` limit: `7` |
| **`Food TC`**                  | Board (`Status`) | `label:area:food`                 | Created (newest first); `Next DTC Agenda` limit: `7` |
| **`Lodging TC`**               | Board (`Status`) | `label:area:lodging`              | Created (newest first); `Next DTC Agenda` limit: `7` |
| **`Community Spotlight Pool`** | Table            | `track:"Community Spotlight"`     | `Priority Score` (descending)                        |

### `Status` Columns

| Column                      | Color  | Purpose                                                                                                         |
| :-------------------------- | :----- | :-------------------------------------------------------------------------------------------------------------- |
| **`Triage / Unscheduled`**  | Gray   | Default intake state set by GitHub Projects' built-in _Item added to project_ workflow.                         |
| **`Next DTC Agenda`**       | Orange | Queued for discussion at the upcoming meeting.                                                                  |
| **`Approved`**              | Green  | Approved in the meeting; `gov:tc-meeting` removed and circle-back comment posted once `meeting-minutes` merges. |
| **`Follow-up / Revisions`** | Purple | Direction approved with revisions or follow-up requested.                                                       |
| **`Redirected / Declined`** | Red    | Redirected to a Domain Working Group / self-hosted extension or declined.                                       |
| **`Closed / Merged`**       | Gray   | Automatically set by GitHub Projects' built-in _Item closed_ and _Pull request merged_ workflows.               |

### Built-in Workflows & Permissions

- **Built-in Project Workflows:**
  - _Auto-add to project_: `is:issue,pr is:open label:gov:tc-meeting,community-spotlight`
  - _Item added to project_: sets `Status = Triage / Unscheduled`
  - _Item closed_ & _Pull request merged_: sets `Status = Closed / Merged`
  - _Auto-archive items_: enabled
- **Team Access:** Organization base role `Read`; `@devops-maintainers` granted `Admin`; Domain Technical Council teams (`@shopping-tech-council`, `@payments-tech-council`, `@food-tech-council`, `@lodging-tech-council`) granted `Write`.
- **Scheduled Sync (`.github/workflows/dtc-pipeline.yml`):**
  - Every 15 minutes: `sync-agenda-assignees --apply` resolves the Technical Council member who moved each card into `Next DTC Agenda` via `ProjectV2ItemStatusChangedEvent` timeline history, assigns them to the Issue or Pull Request, and stamps `Track = General Track` on open `gov:tc-meeting` items.
  - Daily at 06:00 UTC: `scan-spotlight --apply` refreshes Community Spotlight eligibility and syncs `Track = Community Spotlight` and `Priority Score` onto the Project board without applying repository labels on `ucp`.

## Community Spotlight Selection

1. **Gate 1 (External Affiliation):** Excludes members of UCP governance and maintainer teams (`@*-tech-council`, `@governance-council`, `@maintainers`, organization members), companies listed in `MAINTAINERS.md`, matching corporate email domains, and bot accounts.
2. **Gate 2 (Governance Scope):** Bundles linked Proposal Issues and Pull Requests; matches Pull Requests carrying `gov:needs-tc-review` or `gov:tc-meeting`, plus standalone proposal issues carrying `area:<domain>` and a proposal prefix or label.
3. **Gate 3 (Baseline Readiness & Hygiene):** Requires non-draft Pull Requests without merge conflicts, passing contributor license agreement (`cla/google`) and validation checks, or structured proposal issue bodies (`>= 400` characters with template headers), and excludes `status:blocked`, `status:stale`, and `wontfix`.
4. **100-Point Priority Formula (Milestone-Blind):**

$$\text{Priority Score (0–100)} = \text{Readiness (0–40)} + \text{Capped Traction (0–30)} + \text{Wait-Time Boost (0–30)} - \text{Cooldown (0 or 30)}$$

## Usage

```bash
# Run unit tests
uv run python -m unittest discover -s org-tools/dtc-pipeline/tests -v

# Run Community Spotlight scan (read-only preview, or --apply to sync Project v2)
uv run python org-tools/dtc-pipeline/scripts/dtc_pipeline.py scan-spotlight --org Universal-Commerce-Protocol --repo ucp

# Provision or clone a GitHub Project v2 board
uv run python org-tools/dtc-pipeline/scripts/dtc_pipeline.py provision-project \
  --owner Universal-Commerce-Protocol --title "DTC Review Pipeline" --public \
  --admin-teams devops-maintainers --writer-teams shopping-tech-council

# Restore canonical 5-view filters and visible fields
uv run python org-tools/dtc-pipeline/scripts/dtc_pipeline.py configure-views --project-id PVT_...

# Sync Next DTC Agenda assignees and General Track field
uv run python org-tools/dtc-pipeline/scripts/dtc_pipeline.py sync-agenda-assignees --project-id PVT_... --apply
```
