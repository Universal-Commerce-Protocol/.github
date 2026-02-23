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

import os

from dotenv import load_dotenv

load_dotenv(override=True)

GITHUB_BASE_URL = "https://api.github.com"

GITHUB_TOKEN = os.getenv("GITHUB_TOKEN")
if not GITHUB_TOKEN:
    raise ValueError("GITHUB_TOKEN environment variable not set")

GOOGLE_API_KEY = os.getenv("GOOGLE_API_KEY")
if not GOOGLE_API_KEY:
    raise ValueError("GOOGLE_API_KEY environment variable not set")

OWNER = os.getenv("OWNER")
REPO = os.getenv("REPO")
EVENT_NAME = os.getenv("EVENT_NAME")
ISSUE_NUMBER = os.getenv("ISSUE_NUMBER")
ISSUE_TITLE = os.getenv("ISSUE_TITLE")
ISSUE_BODY = os.getenv("ISSUE_BODY")
ISSUE_COUNT_TO_PROCESS = os.getenv("ISSUE_COUNT_TO_PROCESS")

IS_INTERACTIVE = os.environ.get("INTERACTIVE", "1").lower() in ["true", "1"]
