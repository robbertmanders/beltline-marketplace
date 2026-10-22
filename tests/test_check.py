import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

import check  # noqa: E402

AGENT = "---\nname: Build\noutcomes:\n  - name: done\n    then: next\n---\nBuild the change.\n"


def belt(**changes):
    value = {
        "id": "issues", "version": 1, "name": "Issues", "base": "", "afk": "global",
        "triggers": [{"id": "1", "repos": [], "trigger": {"kind": "issues", "label": "agent"}}],
        "stages": [{"id": "build", "agent": {"id": "build", "version": 1}}],
    }
    value.update(changes)
    return json.dumps(value)


class CheckTreeTest(unittest.TestCase):
    def setUp(self):
        self.root = Path(tempfile.mkdtemp())

    def write(self, path, text):
        target = self.root / path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(text)

    def test_a_shared_belt_with_its_agent_passes(self):
        self.write("belts/issues/v1.json", belt())
        self.write("agents/build/v1.md", AGENT)
        self.assertEqual(check.check_tree(self.root), [])

    def test_private_setup_is_refused(self):
        self.write("belts/issues/v1.json", belt(
            base="main", origin={"repository": "me/lib"}, repositoryBases={"me/app": "dev"},
            triggers=[{"id": "1", "repos": ["me/app"], "trigger": {"kind": "issues"}}]))
        self.write("agents/build/v1.md", AGENT.replace("name: Build", "name: Build\norigin: me/lib"))
        problems = "\n".join(check.check_tree(self.root))
        for word in ("repos", "base", "repositoryBases", "`origin`", "frontmatter"):
            self.assertIn(word, problems)

    def test_paths_ids_and_pins_are_checked(self):
        self.write("belts/issues/v1.json", belt(version=2))
        self.write("belts/notes.txt", "x")
        self.write("agents/build/v1.md", "no frontmatter")
        self.write("belts/other/v1.json", belt(id="other", stages=[{"agent": {"id": "gone", "version": 3}}]))
        problems = "\n".join(check.check_tree(self.root))
        self.assertIn("must match the path", problems)
        self.assertIn("belts/notes.txt: expected", problems)
        self.assertIn("starts with frontmatter", problems)
        self.assertIn("pins agent gone v3", problems)


class CheckPublishedTest(unittest.TestCase):
    def git(self, *args):
        subprocess.run(["git", *args], cwd=self.root, check=True, capture_output=True)

    def setUp(self):
        self.root = Path(tempfile.mkdtemp())
        self.git("init", "-q", "-b", "main")
        self.git("config", "user.email", "test@example.com")
        self.git("config", "user.name", "Test")
        (self.root / "agents/build").mkdir(parents=True)
        (self.root / "agents/build/v1.md").write_text(AGENT)
        self.git("add", ".")
        self.git("commit", "-q", "-m", "v1")
        self.git("checkout", "-q", "-b", "change")

    def test_adding_the_next_version_passes(self):
        (self.root / "agents/build/v2.md").write_text(AGENT)
        self.git("add", ".")
        self.git("commit", "-q", "-m", "v2")
        self.assertEqual(check.check_published(self.root, "main"), [])

    def test_changing_or_removing_a_version_fails(self):
        (self.root / "agents/build/v1.md").write_text(AGENT + "More.\n")
        self.git("commit", "-q", "-am", "edit")
        self.assertEqual(len(check.check_published(self.root, "main")), 1)
        self.git("rm", "-q", "agents/build/v1.md")
        self.git("commit", "-q", "-m", "remove")
        self.assertEqual(len(check.check_published(self.root, "main")), 1)


if __name__ == "__main__":
    unittest.main()
