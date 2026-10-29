# UCP DTC Review Pipeline & Community Spotlight Engine

Implements the governance workflow for surfacing and resolving Issues and Pull Requests in weekly Domain Technical Council (DTC) meetings across `Universal-Commerce-Protocol/ucp`:

1. **General DTC Escalation & Native `Next DTC Agenda` Column Gate**
   - Embeds the framing check directly into Column 2 (**`Next DTC Agenda`**, Orange, with column subtitle _"`⚠️ Confirm Framing Comment (or self-contained body) is in place before moving here.`"_) — 100% native in GitHub Projects UI with zero custom badge fields, comment scraping, webhooks, or bot noise on PR threads.
2. **Unified 5-View GitHub Project v2 Architecture (`UCP DTC Review Pipeline`)**
   - Provisions and configures a **single Kanban Board per vertical** (`Shopping TC`, `Payments TC`, `Food TC`, `Lodging TC`) with a **6-column `Status` workflow** (handling triage, next-meeting agenda slotting, and post-meeting resolution outcomes in one board view with zero custom date or Iteration fields):
     1. `Triage / Unscheduled` (Gray — set automatically by GitHub Projects' built-in _Item added to project_ workflow)
     2. `Next DTC Agenda` (Orange — `⚠️ Confirm Framing Comment (or self-contained body) is in place before moving here.`; queued for the upcoming weekly meeting, capped at 5–7 items via GitHub Projects' native Board Column Limit)
     3. `Approved` (Green — approved by DTC; `gov:tc-meeting` removed and circle-back comment posted once `meeting-minutes` merges)
     4. `Follow-up / Revisions` (Purple — discussed in DTC; direction approved with revisions or follow-up requested)
     5. `Redirected / Declined` (Red — redirected to a Domain Working Group / self-hosted extension or declined)
     6. `Closed / Merged` (Gray — set automatically by GitHub Projects' built-in _Item closed_ and _Pull request merged_ workflows)
   - Configures 5 views total: the 4 per-vertical Kanban boards (`Shopping TC`, `Payments TC`, `Food TC`, `Lodging TC`, grouped by `Status`) plus the cross-vertical `Community Spotlight Pool` Table view, surfacing `Track` (`General Track` | `Community Spotlight`), `Priority Score` (`NUMBER`), and the native repository `Milestone` field across all 5 views.
   - Orders General Track `T - 24h` agenda slotting by Release Train Milestone urgency (`Active Milestone` [breaking `!` changes first due to the 2-week public notice window, then `area:common` items requiring GC sign-off] $\rightarrow$ `Next Milestone` $\rightarrow$ `No Milestone`), while keeping the 100-point Community Spotlight heuristic strictly Milestone-blind so external contributors are never penalized for lacking internal Milestone sponsorship.
3. **Dedicated Community Contribution Track ("Community Spotlight")**
   - **Gate 1 (Non-DTC Corporate Affiliation):** Queries the GitHub Org Teams API (`@shopping-tech-council`, `@payments-tech-council`, `@food-tech-council`, `@lodging-tech-council`, `@governance-council`, `@maintainers`), parses `MAINTAINERS.md` for excluded member companies, inspects GitHub user `company` and email domains, and excludes bots.
   - **Gate 2 (DTC Governance Scope Check):** Bundles linked Proposal Issues and PRs; matches PRs carrying `gov:needs-tc-review` or `gov:tc-meeting` (applied by `.github/org-tools/governance`), plus standalone proposal issues carrying `area:<domain>` and proposal prefixes/labels.
   - **Gate 3 (Baseline Readiness & Hygiene Gate):** Enforces non-draft state, clean merge state (`mergeable_state != "dirty"`), passing `cla/google` and validation CI checks, structured proposal issue headers (`enhancement-proposal.yml` / `feature-request.yml`), and excludes items carrying `status:blocked`, `status:stale`, or `wontfix`.
   - **100-Point Deterministic Priority Formula:**
     $$\text{Priority Score (0–100)} = \text{Readiness (0–40)} + \text{Capped Traction (0–30)} + \text{Wait-Time Boost (0–30)} - \text{Cooldown (0 or 30)}$$

## Usage

### Run Unit Tests

```bash
uv run python -m unittest discover -s org-tools/dtc-pipeline/tests -v
```

### Run Community Spotlight Scan (Read-Only)

```bash
uv run python org-tools/dtc-pipeline/scripts/dtc_pipeline.py scan-spotlight --org Universal-Commerce-Protocol --repo ucp
```

### Provision or Clone a GitHub Project v2 Board

```bash
uv run python org-tools/dtc-pipeline/scripts/dtc_pipeline.py provision-project --owner Universal-Commerce-Protocol --title "UCP DTC Review Pipeline" --public
```

### Configure the 5 Project Views

```bash
uv run python org-tools/dtc-pipeline/scripts/dtc_pipeline.py configure-views --project-id PVT_...
```

### Auto-Assign TC Member Who Moved Items to `Next DTC Agenda`

```bash
uv run python org-tools/dtc-pipeline/scripts/dtc_pipeline.py sync-agenda-assignees --project-id PVT_... --apply
```
