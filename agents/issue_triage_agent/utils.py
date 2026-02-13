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

from typing import Any

from issue_triage_agent.settings import GITHUB_TOKEN
import requests
from tenacity import retry
from tenacity import retry_if_exception_type
from tenacity import stop_after_attempt
from tenacity import wait_fixed

headers = {
    "Authorization": f"token {GITHUB_TOKEN}",
    "Accept": "application/vnd.github.v3+json",
}


@retry(
    retry=retry_if_exception_type(requests.exceptions.RequestException),
    stop=stop_after_attempt(3),
    wait=wait_fixed(2),
)
def get_request(url: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
    if params is None:
        params = {}
    response = requests.get(url, headers=headers, params=params, timeout=60)
    response.raise_for_status()
    return response.json()


@retry(
    retry=retry_if_exception_type(requests.exceptions.RequestException),
    stop=stop_after_attempt(3),
    wait=wait_fixed(2),
)
def post_request(url: str, payload: Any) -> dict[str, Any]:
    response = requests.post(url, headers=headers, json=payload, timeout=60)
    response.raise_for_status()
    return response.json()


@retry(
    retry=retry_if_exception_type(requests.exceptions.RequestException),
    stop=stop_after_attempt(3),
    wait=wait_fixed(2),
)
def patch_request(url: str, payload: Any) -> dict[str, Any]:
    response = requests.patch(url, headers=headers, json=payload, timeout=60)
    response.raise_for_status()
    return response.json()


def error_response(error_message: str) -> dict[str, Any]:
    return {"status": "error", "message": error_message}


def parse_number_string(number_str: str | None, default_value: int = 0) -> int:
    """Parse a number from the given string."""
    if number_str is None:
        return default_value
    try:
        return int(number_str)
    except ValueError:
        print(
            f"Warning: Invalid number string: {number_str}. Defaulting to"
            f" {default_value}."
        )
        return default_value

def read_file(file_path: str) -> str:
    """Read the content of a file."""
    try:
        with open(file_path, "r") as f:
            return f.read()
    except FileNotFoundError:
        return f"File not found: {file_path}"
