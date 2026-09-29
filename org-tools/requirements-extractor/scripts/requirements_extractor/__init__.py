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

"""Extract normative requirements from UCP specification prose.

Converts RFC 2119 obligations written in Markdown into a machine-readable
catalog. Each requirement carries two identifiers: a readable, positional
`id` such as REQ-CHECKOUT-WARNING-PRESENTATION-03 for tests to bind to, and a
`content_digest` derived from the normalized clause alone, so routine
editorial changes (re-wrapping a paragraph, moving a file, re-styling
emphasis) do not change it.

The pipeline is five stages, each owning one module:

  parser      Markdown -> Clause candidates, with code blocks excluded
  classifier  Which candidates are normative, and at what obligation level
  metadata    Actor, referenced schema fields, and conditions
  identity    Readable identifiers and content digests
  catalog     Serialization of the catalog and the diagnostics report

Scope is currently the checkout capability. See config.SPEC_DIRS.
"""
