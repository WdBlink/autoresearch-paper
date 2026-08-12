from pathlib import Path
import unittest

from tests.skill_contract_helpers import parse_frontmatter


class SkillContractHelperTests(unittest.TestCase):
    def test_parse_frontmatter_returns_metadata_and_body(self):
        metadata, body = parse_frontmatter(
            "---\nname: sample-skill\ndescription: Use when a sample is needed.\n---\n\n# Sample\n"
        )
        self.assertEqual(metadata, {
            "name": "sample-skill",
            "description": "Use when a sample is needed.",
        })
        self.assertEqual(body.strip(), "# Sample")
