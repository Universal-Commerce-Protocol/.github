#!/usr/bin/env python3
# /// script
# dependencies = [
#   "PyGithub",
#   "PyYAML",
# ]
# ///
"""
Sync GitHub Labels (PyGithub edition)
-------------------------------------
A PyGithub-based Python script to synchronize label configurations from
YAML files (general-labels.yml and triage-labels.yml) to one or more GitHub
repositories in an organization.
"""

import argparse
import logging
import re
import sys
from typing import Any, Dict, List, Optional, Set
import yaml

from github import Auth, Github, GithubException

# Setup logging
logging.basicConfig(level=logging.INFO, format="%(message)s")
logger = logging.getLogger("sync_labels")


def parse_yaml_labels(file_path: str) -> List[Dict[str, Any]]:
    """
    Parses YAML label configurations using PyYAML.
    Expects a list of blocks, each containing:
      - name: label-name
        color: 'hex' (or hex without quotes)
        description: "description string" (optional)
        aliases: (optional list or string)
    """
    with open(file_path, "r", encoding="utf-8") as f:
        data = yaml.safe_load(f)

    if not data:
        return []

    labels: List[Dict[str, Any]] = []
    for item in data:
        if not isinstance(item, dict):
            continue
        name = item.get("name", "")
        name_str = str(name).strip() if name is not None else ""

        color = item.get("color")
        if color is not None and not isinstance(color, str):
            raise ValueError(
                f"Configuration Error: The color value for label '{name_str}' must be enclosed in quotes (e.g., color: \"{color}\")."
            )
        color_str = str(color).strip() if color is not None else ""

        description = item.get("description", "")
        description_str = str(description).strip() if description is not None else ""

        raw_aliases = item.get("aliases") or []
        aliases: List[str] = []
        if isinstance(raw_aliases, str):
            aliases = [a.strip() for a in raw_aliases.split(",") if a.strip()]
        elif isinstance(raw_aliases, list):
            aliases = [str(a).strip() for a in raw_aliases if str(a).strip()]

        if name_str:
            labels.append(
                {
                    "name": name_str,
                    "color": color_str,
                    "description": description_str,
                    "aliases": aliases,
                    "file_path": file_path,
                }
            )
    return labels


def validate_and_check_conflicts(
    labels: List[Dict[str, Any]], check_file_context: bool = True
) -> None:
    """
    Validates the aggregated label set for schema compliance, duplicates, alias conflicts, and alias loop cycles.
    If check_file_context is True, it will also perform local syntactic/structural checks relative to labels in the same file.
    Raises ValueError with details including file origins if any conflict or schema issue is found.
    """
    seen_names: Dict[str, Dict[str, Any]] = {}
    alias_to_name: Dict[str, str] = {}
    alias_to_file: Dict[str, str] = {}

    # Hex color regex pattern
    hex_color_pattern = re.compile(r"^[0-9a-fA-F]{6}$")

    # 1. Collect defined names for local file context validations if needed
    file_to_names: Dict[str, Set[str]] = {}
    if check_file_context:
        for label in labels:
            name = label["name"]
            file_path = label.get("file_path") or "unknown configuration file"
            if file_path not in file_to_names:
                file_to_names[file_path] = set()
            file_to_names[file_path].add(name)

    for label in labels:
        name = label["name"]
        color = (label.get("color") or "").strip()
        desc = label.get("description") or ""
        aliases = label.get("aliases") or []
        file_path = label.get("file_path") or "unknown configuration file"

        # Schema validations
        # 1. Empty or invalid label name
        if not name or not name.strip():
            raise ValueError(
                f"Schema Error: Label name cannot be empty or blank (found in '{file_path}')."
            )

        # 2. Invalid Hex Color validation
        if not color:
            raise ValueError(
                f"Schema Error: Label '{name}' defined in '{file_path}' is missing a hex color code."
            )
        if not hex_color_pattern.match(color):
            raise ValueError(
                f"Schema Error: Label '{name}' defined in '{file_path}' has an invalid hex color '#{color}'. "
                f"Color must be a valid 6-character hex code (e.g., 'd73a4a')."
            )

        # Check exact duplicates or conflicting duplicates
        if name in seen_names:
            existing = seen_names[name]
            existing_color = (existing.get("color") or "").strip().lower()
            existing_desc = existing.get("description") or ""
            existing_aliases = sorted(existing.get("aliases") or [])
            existing_file = existing.get("file_path") or "unknown configuration file"

            if (
                existing_color != color.lower()
                or existing_desc != desc
                or existing_aliases != sorted(aliases)
            ):
                raise ValueError(
                    f"Conflict detected for label '{name}':\n"
                    f"  Defined in '{existing_file}': Color #{existing_color}, Desc '{existing_desc}', Aliases {existing_aliases}\n"
                    f"  Defined in '{file_path}': Color #{color}, Desc '{desc}', Aliases {aliases}"
                )
        else:
            seen_names[name] = label

        # Check aliases
        for alias in aliases:
            # Check for simple loop: label alias is its own name
            if alias == name:
                raise ValueError(
                    f"Conflict: Label '{name}' in '{file_path}' cannot have itself as an alias."
                )

            if check_file_context and file_path in file_to_names:
                if alias in file_to_names[file_path]:
                    raise ValueError(
                        f"Conflict in '{file_path}': Alias '{alias}' for label '{name}' "
                        f"is already defined as a separate label name in the same file."
                    )

            if alias in alias_to_name and alias_to_name[alias] != name:
                other_name = alias_to_name[alias]
                other_file = alias_to_file[alias]
                raise ValueError(
                    f"Conflict: Alias '{alias}' is defined for both label '{name}' (in '{file_path}') "
                    f"and label '{other_name}' (in '{other_file}')."
                )
            alias_to_name[alias] = name
            alias_to_file[alias] = file_path

    # Topological/Cycle check for indirect loops
    for label in labels:
        name = label["name"]
        file_path = label.get("file_path") or "unknown configuration file"
        path = [name]
        curr = name
        while curr in alias_to_name:
            next_step = alias_to_name[curr]
            if next_step in path:
                path.append(next_step)
                cycle_str = " -> ".join(path)
                raise ValueError(
                    f"Conflict: Cyclic alias dependency detected starting at label '{name}' in '{file_path}': {cycle_str}"
                )
            path.append(next_step)
            curr = next_step

    # Final pass for standard name/alias conflicts
    for label in labels:
        name = label["name"]
        file_path = label.get("file_path") or "unknown configuration file"
        aliases = label.get("aliases") or []

        for alias in aliases:
            if alias in seen_names:
                target_file = (
                    seen_names[alias].get("file_path") or "unknown configuration file"
                )
                raise ValueError(
                    f"Conflict: Alias '{alias}' defined for label '{name}' in '{file_path}' "
                    f"conflicts with existing label name '{alias}' defined in '{target_file}'."
                )

        if name in alias_to_name:
            target_label = alias_to_name[name]
            target_file = alias_to_file[name]
            raise ValueError(
                f"Conflict: Label name '{name}' defined in '{file_path}' is already registered "
                f"as an alias for label '{target_label}' in '{target_file}'."
            )


def merge_labels(
    list_a: List[Dict[str, Any]], list_b: List[Dict[str, Any]]
) -> List[Dict[str, Any]]:
    """
    Merge two lists of label dicts. Validates the entire combined set first for consistency and conflicts before merging.
    """
    # 1. Validate the aggregated list of all loaded labels first
    all_labels = list_a + list_b
    validate_and_check_conflicts(all_labels)

    # 2. If no issues found, safely perform the merge
    merged: Dict[str, Dict[str, Any]] = {}
    for label in list_a:
        merged[label["name"]] = label

    for label in list_b:
        merged[label["name"]] = label

    return list(merged.values())


def verify_access(
    org_name: str,
    repo_names: Optional[List[str]],
    token: str,
    exclude_repos: Optional[List[str]] = None,
) -> List[Any]:
    """
    Verifies API access to the organization and target repositories before starting operations.
    Returns the list of resolved repository objects.
    """
    logger.info(f"Verifying API access for organization '{org_name}'...")
    auth = Auth.Token(token)
    g = Github(auth=auth)
    try:
        org = g.get_organization(org_name)
    except GithubException as e:
        logger.error(
            f"Access Verification Failed: Cannot fetch organization '{org_name}': {e}"
        )
        sys.exit(1)

    target_repos = []
    if repo_names:
        for rname in repo_names:
            try:
                repo = org.get_repo(rname)
                # Verify permissions if possible, or try a minimal read call
                _ = repo.permissions
                target_repos.append(repo)
            except GithubException as e:
                logger.error(
                    f"Access Verification Failed: Cannot access repository '{rname}' in org '{org_name}': {e}"
                )
                sys.exit(1)
    else:
        try:
            target_repos = list(org.get_repos())
        except GithubException as e:
            logger.error(
                f"Access Verification Failed: Cannot list repositories under organization '{org_name}': {e}"
            )
            sys.exit(1)

    if exclude_repos:
        target_repos = [r for r in target_repos if r.name not in exclude_repos]

    logger.info(
        "Access verification completed successfully. All target repositories are accessible."
    )
    return target_repos


def sync_labels(
    org_name: str,
    target_repos: List[Any],
    target_labels: List[Dict[str, Any]],
    dry_run: bool = True,
) -> None:
    logger.info(
        f"\n=== Starting Label Sync for Org: {org_name} (Dry Run: {dry_run}) ==="
    )

    for repo in target_repos:
        logger.info(f"\nSyncing repository: {repo.name}...")
        try:
            existing = {label.name: label for label in repo.get_labels()}
        except GithubException as e:
            logger.warning(f"  Skipping due to error fetching labels: {e}")
            continue

        # Keep track of labels we renamed or processed to avoid duplicate operations
        processed_labels: Set[str] = set()

        for target in target_labels:
            name = target["name"]
            color = target.get("color") or "ffffff"
            desc = target.get("description") or ""
            aliases = target.get("aliases") or []

            # 1. Check if label needs to be renamed from an alias
            renamed = False
            for alias in aliases:
                if alias in existing and name not in existing:
                    logger.info(
                        f"  [RENAME] Old label '{alias}' -> New label '{name}' (Color: #{color}, Desc: '{desc}')"
                    )
                    if not dry_run:
                        try:
                            label_obj = existing[alias]
                            label_obj.edit(name=name, color=color, description=desc)
                            # Update existing map
                            existing[name] = label_obj
                            del existing[alias]
                        except GithubException as e:
                            logger.error(
                                f"    Failed to rename label '{alias}' to '{name}': {e}"
                            )
                    renamed = True
                    processed_labels.add(name)
                    break

            if renamed:
                continue

            # 2. Standard Create/Update Logic
            if name not in existing:
                logger.info(
                    f"  [CREATE] Label '{name}' (Color: #{color}, Desc: '{desc}')"
                )
                if not dry_run:
                    try:
                        repo.create_label(name=name, color=color, description=desc)
                    except GithubException as e:
                        logger.error(f"    Failed to create label: {e}")
            else:
                curr = existing[name]
                curr_color = curr.color.lower()
                curr_desc = curr.description or ""

                if curr_color != color.lower() or curr_desc != desc:
                    logger.info(f"  [UPDATE] Label '{name}':")
                    if curr_color != color.lower():
                        logger.info(f"    Color: #{curr_color} -> #{color}")
                    if curr_desc != desc:
                        logger.info(f"    Desc: '{curr_desc}' -> '{desc}'")
                    if not dry_run:
                        try:
                            curr.edit(name=name, color=color, description=desc)
                        except GithubException as e:
                            logger.error(f"    Failed to update label: {e}")


def main() -> None:
    description_text = """
GitHub Label Synchronization Tool.

Note: This tool is strictly ADDITIVE and non-destructive. It will only create
missing labels or update matching labels if their properties (color or description)
differ from the YAML configurations. It will NEVER delete existing labels from your repositories.
"""
    parser = argparse.ArgumentParser(
        description=description_text,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "--token",
        required=True,
        help="Required. Your GitHub Personal Access Token.",
    )
    parser.add_argument(
        "--org",
        required=True,
        help="Required. The target GitHub Organization name.",
    )
    parser.add_argument(
        "--repos",
        help="A comma-separated list of specific repository names to sync.",
    )
    parser.add_argument(
        "--all-repos",
        action="store_true",
        help="Target ALL repositories under the specified GitHub Organization.",
    )
    parser.add_argument(
        "--exclude-repos",
        help="A comma-separated list of repository names to exclude from syncing.",
    )
    parser.add_argument(
        "--apply",
        action="store_true",
        help="Execute synchronization live on GitHub.",
    )
    parser.add_argument(
        "--general-config",
        default="org-tools/labels/general-labels.yml",
        help="Path to general labels YAML config.",
    )
    parser.add_argument(
        "--triage-config",
        default="org-tools/labels/triage-labels.yml",
        help="Path to triage labels YAML config.",
    )

    if len(sys.argv) == 1:
        parser.print_help(sys.stderr)
        sys.exit(1)

    args = parser.parse_args()

    if not args.repos and not args.all_repos:
        parser.error(
            "You must specify target repositories using --repos, or explicitly use the --all-repos flag to sync the entire organization."
        )

    try:
        general_labels = parse_yaml_labels(args.general_config)
        validate_and_check_conflicts(general_labels, check_file_context=True)

        triage_labels = parse_yaml_labels(args.triage_config)
        validate_and_check_conflicts(triage_labels, check_file_context=True)
    except Exception as e:
        logger.error(f"Error parsing or verifying configuration files: {e}")
        sys.exit(1)

    try:
        target_labels = merge_labels(general_labels, triage_labels)
    except ValueError as e:
        logger.error(f"Validation Error: {e}")
        sys.exit(1)

    repos_list = (
        [r.strip() for r in args.repos.split(",") if r.strip()] if args.repos else None
    )
    exclude_list = (
        [r.strip() for r in args.exclude_repos.split(",") if r.strip()]
        if args.exclude_repos
        else None
    )

    # 1. Verify Access first
    target_repos = verify_access(
        org_name=args.org,
        repo_names=repos_list,
        token=args.token,
        exclude_repos=exclude_list,
    )

    # 2. Perform standard label sync
    sync_labels(
        org_name=args.org,
        target_repos=target_repos,
        target_labels=target_labels,
        dry_run=not args.apply,
    )
    logger.info("\nSynchronization execution complete.")


if __name__ == "__main__":
    main()
