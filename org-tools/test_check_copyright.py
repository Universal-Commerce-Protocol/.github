#!/usr/bin/env python3
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

"""Unit tests for check_copyright.py."""

import tempfile
import unittest
from pathlib import Path

# Import the check functions from check_copyright
import check_copyright


class TestCheckCopyright(unittest.TestCase):
    def setUp(self):
        # Create a temporary directory for test files
        self.test_dir = tempfile.TemporaryDirectory()
        self.test_dir_path = Path(self.test_dir.name)

    def tearDown(self):
        self.test_dir.cleanup()

    def create_test_file(self, filename: str, content: str) -> Path:
        file_path = self.test_dir_path / filename
        file_path.write_text(content, encoding="utf-8")
        return file_path

    def test_valid_copyright_header(self):
        content = (
            "# Copyright 2026 UCP Authors\n"
            "# Licensed under the Apache License, Version 2.0\n"
            "\n"
            "print('hello')"
        )
        file_path = self.create_test_file("valid.py", content)
        self.assertTrue(
            check_copyright.check_file(
                file_path, check_copyright.DEFAULT_GENERATED_FILENAME_RE
            )
        )

    def test_valid_apache_license_only(self):
        content = (
            '// Licensed under the Apache License, Version 2.0 (the "License");\n'
            "// you may not use this file except in compliance with the License.\n"
            "console.log('hello');"
        )
        file_path = self.create_test_file("valid.ts", content)
        self.assertTrue(
            check_copyright.check_file(
                file_path, check_copyright.DEFAULT_GENERATED_FILENAME_RE
            )
        )

    def test_copyright_spacing_variations(self):
        cases = [
            "Copyright(c) 2026 UCP Authors",
            "Copyright (c)2026 UCP Authors",
            "Copyright(c)2026 UCP Authors",
        ]
        for content in cases:
            file_path = self.create_test_file("spacing.py", content)
            self.assertTrue(
                check_copyright.check_file(
                    file_path, check_copyright.DEFAULT_GENERATED_FILENAME_RE
                ),
                f"Failed for: {content}"
            )

    def test_missing_copyright_header(self):
        content = "print('hello')"
        file_path = self.create_test_file("invalid.py", content)
        self.assertFalse(
            check_copyright.check_file(
                file_path, check_copyright.DEFAULT_GENERATED_FILENAME_RE
            )
        )

    def test_empty_file_passes(self):
        file_path = self.create_test_file("empty.py", "")
        self.assertTrue(
            check_copyright.check_file(
                file_path, check_copyright.DEFAULT_GENERATED_FILENAME_RE
            )
        )

    def test_untracked_extension_skipped(self):
        file_path = self.create_test_file("image.png", "binarydata")
        self.assertTrue(
            check_copyright.check_file(
                file_path, check_copyright.DEFAULT_GENERATED_FILENAME_RE
            )
        )

    def test_default_generated_filename_passes(self):
        # Default Protobuf / GRPC generated filename format should pass
        content = "print('hello')"
        file_path = self.create_test_file("foo_pb2.py", content)
        self.assertTrue(
            check_copyright.check_file(
                file_path, check_copyright.DEFAULT_GENERATED_FILENAME_RE
            )
        )

        file_path2 = self.create_test_file("foo_pb2_grpc.py", content)
        self.assertTrue(
            check_copyright.check_file(
                file_path2, check_copyright.DEFAULT_GENERATED_FILENAME_RE
            )
        )

    def test_custom_exclude_filename_regex_override(self):
        import re

        content = "print('hello')"
        file_path = self.create_test_file("spec_generated.ts", content)

        # 1. Under default regex, spec_generated.ts should FAIL (no copyright header and doesn't match default pb2 regex)
        self.assertFalse(
            check_copyright.check_file(
                file_path, check_copyright.DEFAULT_GENERATED_FILENAME_RE
            )
        )

        # 2. Under combined regex, spec_generated.ts should PASS
        custom_pattern = r"^(spec_generated\.[a-z]+)$"
        combined_pattern = f"({custom_pattern}|{check_copyright.DEFAULT_GENERATED_FILENAME_RE.pattern})"
        combined_re = re.compile(combined_pattern, re.IGNORECASE)
        self.assertTrue(check_copyright.check_file(file_path, combined_re))

        # 3. Default Protobuf files should STILL pass under combined regex
        protobuf_path = self.create_test_file("foo_pb2.py", content)
        self.assertTrue(check_copyright.check_file(protobuf_path, combined_re))

    def test_generated_content_marker_passes(self):
        content = (
            "# This file is auto-generated by some generator tool.\n"
            "# DO NOT EDIT.\n"
            "print('hello')"
        )
        file_path = self.create_test_file("auto_gen.py", content)
        self.assertTrue(
            check_copyright.check_file(
                file_path, check_copyright.DEFAULT_GENERATED_FILENAME_RE
            )
        )

    def test_datamodel_codegen_marker_passes(self):
        content = "# generated by datamodel-codegen\nprint('hello')"
        file_path = self.create_test_file("codegen.py", content)
        self.assertTrue(
            check_copyright.check_file(
                file_path, check_copyright.DEFAULT_GENERATED_FILENAME_RE
            )
        )

    def test_c_style_single_line_marker_passes(self):
        content = "/* @generated */\nprint('hello')"
        file_path = self.create_test_file("codegen.css", content)
        self.assertTrue(
            check_copyright.check_file(
                file_path, check_copyright.DEFAULT_GENERATED_FILENAME_RE
            )
        )

    def test_html_marker_passes(self):
        content = "<!-- @generated -->\n<html></html>"
        file_path = self.create_test_file("codegen.html", content)
        self.assertTrue(
            check_copyright.check_file(
                file_path, check_copyright.DEFAULT_GENERATED_FILENAME_RE
            )
        )


if __name__ == "__main__":
    unittest.main()
