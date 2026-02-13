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

# Maps the category label to the team responsible for it (defined in team_members.py)
CATEGORY_TO_OWNER = {
    "core-protocol": "technical-committee",
    "governance": "governance-committee",
    "capability": "maintainers",
    "documentation": "maintainers",
    "infrastructure": "devops-maintainers",
    "maintenance": "devops-maintainers",
    "sdk": "devops-maintainers",
    "samples-conformance": "maintainers",
    "ucp-schema": "devops-maintainers",
}

# Guidance for the AI to determine which category an issue belongs to
CATEGORY_GUIDELINES = """
      Category rubric and disambiguation rules:
      - "core-protocol": Issues related to base communication layer, global context, breaking changes or major refactors.
      - "governance": Issues related to project governance, contribution guidelines, licensing.
      - "capability": Issues suggesting new schemas (Discovery, Cart, etc.) or extensions, or bugs in the semantic content of existing ones.
      - "documentation": Issues about documentation (README, guides).
      - "infrastructure": Issues about CI/CD, linters, build scripts, repo setup.
      - "maintenance": Issues about version bumps, lockfile updates, minor bug fixes, dependency updates.
      - "sdk": Issues related to language specific SDKs.
      - "samples-conformance": Issues about samples or conformance suite.
      - "ucp-schema": Issues related to the ucp-schema CLI tool, validator, schema resolution logic, or Rust library.

      When unsure between categories, prefer the most specific match. If a category
      cannot be assigned confidently, do not call the labeling tool.
"""
