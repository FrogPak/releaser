"""The version in the code, the newest changelog entry and a pushed release tag must agree."""
import os
import re
import unittest
from pathlib import Path

from releaser import __version__

ROOT = Path(__file__).resolve().parent.parent


class VersionTests(unittest.TestCase):
    def test_changelog_matches(self):
        newest = re.search(r"^## (\S+)", (ROOT / "CHANGELOG.md").read_text(), re.M).group(1)
        self.assertEqual(newest, __version__,
                         f"CHANGELOG.md's newest entry is {newest}; set __version__ in releaser/__init__.py to match")

    def test_release_tag_matches(self):
        ref = os.environ.get("GITHUB_REF", "")
        if not re.fullmatch(r"refs/tags/v\d+\.\d+\.\d+", ref):
            self.skipTest("not a release tag")
        self.assertEqual(ref.removeprefix("refs/tags/v"), __version__)


if __name__ == "__main__":
    unittest.main()
