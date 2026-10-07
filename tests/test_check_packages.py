"""Checker coverage for marketplace package proposals."""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from contextlib import contextmanager
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT / "tests"))

import check_packages  # noqa: E402
from package_samples import (  # noqa: E402
    agent_markdown,
    agent_package,
    belt,
    belt_package,
    dumps,
    factory_package,
    factory_without_belts,
    manifest,
)

ZERO = "0" * 40
SCRIPT = ROOT / "scripts" / "check_packages.py"
# The catalog reviewed for issue #29 and its packages tree at that commit.
BASELINE_COMMIT = "acaf61e89f5fc2588afb25e658a87d2dc1a48d1b"
BASELINE_PACKAGES_TREE = "738d7d92d1d0bd9c22e91b4bd4c0591531639631"


def entries(files: dict[str, bytes]) -> dict[str, check_packages.Entry]:
    return {path: check_packages.make_entry(content) for path, content in files.items()}


def check(files: dict[str, bytes], base: dict[str, bytes] | None = None) -> list[check_packages.Diagnostic]:
    return check_packages.evaluate(entries(files), entries(base or {}))


def messages(diagnostics: list[check_packages.Diagnostic], severity: str = "error") -> list[str]:
    return [item.message for item in diagnostics if item.severity == severity]


def rendered(diagnostics: list[check_packages.Diagnostic]) -> str:
    return "\n".join(check_packages.format_annotation(item) for item in diagnostics)


def replace_json(files: dict[str, bytes], suffix: str, mutate) -> dict[str, bytes]:
    path = next(item for item in files if item.endswith(suffix))
    value = json.loads(files[path])
    mutate(value)
    files[path] = dumps(value)
    return files


class Samples(unittest.TestCase):
    def test_on_disk_fixtures_match_the_builders_and_pass(self) -> None:
        expected = {
            "valid-belt": belt_package(),
            "valid-agent": agent_package(),
            "valid-factory": factory_package(),
        }
        for name, built in expected.items():
            with self.subTest(name=name):
                loaded = load_fixture(name)
                self.assertEqual(loaded, built)
                self.assertEqual(check(loaded), [])

    def test_factory_without_belts_and_without_agent_flag_passes(self) -> None:
        self.assertEqual(check(factory_without_belts()), [])

    def test_definition_version_gap_and_unpinned_factory_agent_pass(self) -> None:
        files = factory_without_belts("gap")
        root = "packages/gap/v1"
        files[f"{root}/belts/issues/v1.json"] = dumps(belt(pins=[("triage", 1)]))
        files[f"{root}/belts/issues/state.json"] = dumps({"archived": False, "paused": True})
        files[f"{root}/agents/triage/v1.md"] = agent_markdown("triage", 1)
        files[f"{root}/agents/triage/v4.md"] = agent_markdown("triage", 4)
        self.assertEqual(check(files), [])

    def test_stdlib_only(self) -> None:
        source = SCRIPT.read_text(encoding="utf-8")
        imported = set()
        for line in source.splitlines():
            if line.startswith("import "):
                imported.add(line.split()[1].split(".")[0])
            elif line.startswith("from "):
                imported.add(line.split()[1].split(".")[0])
        allowed = {"__future__", "argparse", "dataclasses", "hashlib", "json", "pathlib", "re", "subprocess", "sys"}
        self.assertLessEqual(imported, allowed)


class ManifestTests(unittest.TestCase):
    def package(self, document: object) -> dict[str, bytes]:
        files = belt_package("desk")
        raw = document if isinstance(document, bytes) else dumps(document)
        files["packages/desk/v1/package.json"] = raw
        return files

    def test_table(self) -> None:
        valid = manifest("desk", "belt", "Desk", "Ships the desk.")
        cases = {
            "missing schemaVersion": {key: value for key, value in valid.items() if key != "schemaVersion"},
            "missing id": {key: value for key, value in valid.items() if key != "id"},
            "missing name": {key: value for key, value in valid.items() if key != "name"},
            "missing kind": {key: value for key, value in valid.items() if key != "kind"},
            "missing summary": {key: value for key, value in valid.items() if key != "summary"},
            "missing author": {key: value for key, value in valid.items() if key != "author"},
            "missing tags": {key: value for key, value in valid.items() if key != "tags"},
            "extra key": {**valid, "license": "secret"},
            "null schemaVersion": {**valid, "schemaVersion": None},
            "null id": {**valid, "id": None},
            "null name": {**valid, "name": None},
            "boolean schemaVersion": {**valid, "schemaVersion": True},
            "float schemaVersion": {**valid, "schemaVersion": 1.0},
            "string schemaVersion": {**valid, "schemaVersion": "1"},
            "unsupported schemaVersion": {**valid, "schemaVersion": 2},
            "id type": {**valid, "id": 1},
            "mismatched id": {**valid, "id": "other"},
            "invalid id": {**valid, "id": "bad id"},
            "blank name": {**valid, "name": "  "},
            "blank summary": {**valid, "summary": ""},
            "multiline summary": {**valid, "summary": "one\ntwo"},
            "unknown kind": {**valid, "kind": "plugin"},
            "kind type": {**valid, "kind": 1},
            "tags type": {**valid, "tags": "issues"},
            "tags null": {**valid, "tags": None},
            "tags item type": {**valid, "tags": [1]},
            "blank tag": {**valid, "tags": ["  "]},
        }
        snippets = {
            "missing schemaVersion": "missing schemaVersion",
            "missing id": "missing id",
            "missing name": "missing name",
            "missing kind": "missing kind",
            "missing summary": "missing summary",
            "missing author": "missing author",
            "missing tags": "missing tags",
            "extra key": "unknown keys license",
            "null schemaVersion": "null schemaVersion",
            "null id": "null id",
            "null name": "null name",
            "boolean schemaVersion": "schemaVersion has the wrong type",
            "float schemaVersion": "schemaVersion has the wrong type",
            "string schemaVersion": "schemaVersion has the wrong type",
            "unsupported schemaVersion": "unsupported schemaVersion 2",
            "id type": "id has the wrong type",
            "mismatched id": "id does not match package directory",
            "invalid id": "invalid id",
            "blank name": "empty name",
            "blank summary": "empty summary",
            "multiline summary": "summary must be a single line",
            "unknown kind": 'unknown kind "plugin"',
            "kind type": "kind has the wrong type",
            "tags type": "tags has the wrong type",
            "tags null": "null tags",
            "tags item type": "tags[0] has the wrong type",
            "blank tag": "tags[0] is blank",
        }
        for name, document in cases.items():
            with self.subTest(name=name):
                found = messages(check(self.package(document)))
                self.assertIn(snippets[name], found)

    def test_empty_tags_pass(self) -> None:
        self.assertEqual(check(agent_package()), [])

    def test_invalid_json_and_utf8(self) -> None:
        self.assertIn("invalid JSON", messages(check(self.package(b"{"))))
        self.assertIn("manifest must be an object", messages(check(self.package(b"[]"))))
        self.assertIn("invalid UTF-8", messages(check(self.package(b"\xff"))))

    def test_two_missing_fields_are_ordered(self) -> None:
        document = manifest("desk", "belt", "Desk", "Ships.")
        del document["author"]
        del document["name"]
        found = messages(check(self.package(document)))
        self.assertEqual(found, ["missing author", "missing name"])


class LayoutTests(unittest.TestCase):
    def test_unsafe_and_unsupported_paths(self) -> None:
        files = belt_package()
        files["packages/issue-flow/v1/notes.txt"] = b"nope\n"
        files["packages/issue-flow/v1/.gitkeep"] = b"\n"
        files["packages/issue-flow/v1/agents/triage/v01.md"] = agent_markdown("triage", 1)
        files["packages/loose.txt"] = b"nope\n"
        files["packages/issue-flow/v1/../secret"] = b"nope\n"
        files["packages/issue-flow/v1/./file"] = b"nope\n"
        files["packages/issue-flow/v1/foo\\bar"] = b"nope\n"
        files["packages/issue-flow/v1//empty"] = b"nope\n"
        found = messages(check(files))
        self.assertIn("unsupported path", found)
        self.assertIn("invalid version number", found)
        self.assertGreaterEqual(found.count("unsafe path"), 4)

    def test_version_directory_names(self) -> None:
        for name in ("v0", "v01"):
            with self.subTest(name=name):
                files = {f"packages/issue-flow/{name}/package.json": b"{}\n"}
                self.assertIn("invalid version number", messages(check(files)))
        files = {"packages/issue-flow/latest/package.json": b"{}\n"}
        self.assertIn("unsupported path", messages(check(files)))

    def test_empty_tree_and_gitkeep_pass(self) -> None:
        self.assertEqual(check({}), [])
        self.assertEqual(check({"packages/.gitkeep": b""}), [])
        self.assertEqual(check({"packages/.gitkeep": b"\n"}, {"packages/.gitkeep": b""}), [])
        self.assertEqual(check({"README.md": b"changed\n"}, {"README.md": b"docs\n"}), [])

    def test_orphan_payload_without_manifest(self) -> None:
        files = {"packages/example/v1/agents/review/v1.md": agent_markdown("review", 1)}
        self.assertIn("missing manifest", messages(check(files)))

    def test_symlink_and_submodule_modes_are_not_read_as_text(self) -> None:
        head = entries(belt_package())
        head["packages/issue-flow/v1/link"] = check_packages.make_entry(None, "120000", "abc")
        head["packages/issue-flow/v1/nested"] = check_packages.make_entry(None, "160000", "def")
        found = messages(check_packages.evaluate(head, {}))
        self.assertIn("symlink", found)
        self.assertIn("submodule", found)

    def test_belt_agent_and_factory_shape(self) -> None:
        files = belt_package()
        files["packages/issue-flow/v1/agents/extra/v1.md"] = agent_markdown("extra", 1)
        self.assertIn("not pinned by the belt", messages(check(files)))

        files = belt_package()
        del files["packages/issue-flow/v1/agents/triage/v1.md"]
        self.assertIn("missing agents/triage/v1.md", messages(check(files)))

        files = belt_package()
        files["packages/issue-flow/v1/belts/other/v1.json"] = dumps(belt(belt_id="other"))
        self.assertIn("expected exactly one belt, found", " ".join(messages(check(files))))

        files = agent_package()
        files["packages/review/v1/agents/other/v1.md"] = agent_markdown("other", 1)
        self.assertTrue(any(message.startswith("expected exactly one agent") for message in messages(check(files))))

        files = {"packages/review/v1/package.json": agent_package()["packages/review/v1/package.json"]}
        self.assertIn("expected exactly one agent, found none", messages(check(files)))

        files = agent_package()
        files["packages/review/v1/belts/issues/v1.json"] = dumps(belt())
        self.assertIn("not part of an agent package", messages(check(files)))

        files = belt_package()
        replace_json(files, "belts/issues/v1.json", lambda obj: obj.__setitem__("id", "other"))
        self.assertIn("id/version disagrees with path", messages(check(files)))

        files = agent_package()
        files["packages/review/v1/agents/review/v1.md"] = b"---\nid: other\nname: Review\n---\n\nHi\n"
        self.assertIn("id/version disagrees with path", messages(check(files)))

        files = belt_package()
        files["packages/issue-flow/v1/belts/issues/v1.json"] = b"{"
        self.assertIn("invalid JSON", messages(check(files)))

        files = agent_package()
        files["packages/review/v1/agents/review/v1.md"] = b"not frontmatter\n"
        self.assertIn("malformed frontmatter", messages(check(files)))

        files = agent_package()
        files["packages/review/v1/agents/review/v1.md"] = b"\xff"
        self.assertIn("invalid UTF-8", messages(check(files)))

        files = belt_package()
        def drop_pin(obj: dict) -> None:
            del obj["stages"][0]["agent"]
        replace_json(files, "belts/issues/v1.json", drop_pin)
        self.assertIn("stage stage-0 has no agent pin", messages(check(files)))

    def test_factory_metadata_flags_and_historical_pins(self) -> None:
        files = factory_package()
        del files["packages/team-setup/v1/agents/triage/v1.md"]
        self.assertIn("missing agents/triage/v1.md", messages(check(files)))

        files = factory_package()
        del files["packages/team-setup/v1/factory.json"]
        self.assertIn("missing manifest", messages(check(files)))

        files = factory_package()
        replace_json(files, "factory.json", lambda obj: obj.__setitem__("origin", "local"))
        self.assertIn("unknown keys origin", messages(check(files)))

        files = factory_package()
        replace_json(files, "factory.json", lambda obj: obj.__setitem__("schemaVersion", True))
        self.assertIn("schemaVersion has the wrong type", messages(check(files)))

        files = factory_package()
        replace_json(files, "factory.json", lambda obj: obj.__setitem__("schemaVersion", 1.0))
        self.assertIn("schemaVersion has the wrong type", messages(check(files)))

        files = factory_package()
        replace_json(files, "factory.json", lambda obj: obj.__setitem__("id", "other"))
        self.assertIn("id does not match package id", messages(check(files)))

        files = factory_package()
        replace_json(files, "factory.json", lambda obj: obj.__setitem__("name", "Other"))
        self.assertIn("name does not match package name", messages(check(files)))

        files = factory_package()
        replace_json(files, "factory.json", lambda obj: obj.__setitem__("name", "  "))
        self.assertIn("empty name", messages(check(files)))

        files = factory_package()
        files["packages/team-setup/v1/belts/ghost/state.json"] = dumps({"archived": False, "paused": True})
        self.assertIn("flag does not belong to an included belt", messages(check(files)))

        files = factory_package()
        files["packages/team-setup/v1/agents/ghost/state.json"] = dumps({"archived": False})
        self.assertIn("flag does not belong to an included agent", messages(check(files)))

        files = factory_package()
        replace_json(files, "belts/issues/state.json", lambda obj: obj.__setitem__("lastFired", "2020-01-01"))
        self.assertIn("unknown keys lastFired", messages(check(files)))

        files = belt_package()
        files["packages/issue-flow/v1/belts/issues/state.json"] = dumps({"archived": False, "paused": True})
        self.assertIn("flag files belong only in a factory package", messages(check(files)))


class StrippingTests(unittest.TestCase):
    def mutate(self, files: dict[str, bytes], fn) -> list[str]:
        replace_json(files, "belts/issues/v1.json", fn)
        return messages(check(files))

    def test_each_stripped_field_fails_for_belt_and_factory(self) -> None:
        cases = {
            "repos nonempty": (lambda obj: obj.__setitem__("repos", ["synthetic/private-repo"]), "repos must be []"),
            "repos omitted": (lambda obj: obj.pop("repos"), "repos must be []"),
            "repos type": (lambda obj: obj.__setitem__("repos", "none"), "repos must be []"),
            "base nonempty": (lambda obj: obj.__setitem__("base", "main"), 'base must be ""'),
            "base omitted": (lambda obj: obj.pop("base"), 'base must be ""'),
            "base type": (lambda obj: obj.__setitem__("base", 1), 'base must be ""'),
            "afk true": (lambda obj: obj.__setitem__("afkEnabled", True), "afkEnabled must be false"),
            "afk omitted": (lambda obj: obj.pop("afkEnabled"), "afkEnabled must be false"),
            "afk type": (lambda obj: obj.__setitem__("afkEnabled", "false"), "afkEnabled must be false"),
            "legacy repos": (
                lambda obj: obj["trigger"].__setitem__("repos", ["synthetic/private-repo"]),
                "trigger repos must be absent or []",
            ),
            "legacy base": (lambda obj: obj["trigger"].__setitem__("base", "develop"), 'trigger base must be absent or ""'),
        }
        for label, (mutate, snippet) in cases.items():
            for builder in (belt_package, factory_package):
                with self.subTest(label=label, package=builder.__name__):
                    self.assertIn(snippet, self.mutate(builder(), mutate))

    def test_empty_legacy_fields_pass(self) -> None:
        files = belt_package()
        replace_json(
            files,
            "belts/issues/v1.json",
            lambda obj: obj["trigger"].update({"repos": [], "base": ""}),
        )
        self.assertEqual(check(files), [])

    def test_older_factory_belt_with_a_private_repository_fails(self) -> None:
        files = factory_package()
        replace_json(files, "belts/issues/v1.json", lambda obj: obj.__setitem__("repos", ["synthetic/private-repo"]))
        self.assertIn("repos must be []", messages(check(files)))


class FlagTests(unittest.TestCase):
    def test_paused_values(self) -> None:
        paused_true = factory_package()
        self.assertEqual(check(paused_true), [])
        archived = factory_package()
        replace_json(archived, "state.json", lambda obj: obj.__setitem__("archived", True))
        self.assertEqual(check(archived), [])

        paused_false = factory_package()
        replace_json(paused_false, "state.json", lambda obj: obj.__setitem__("paused", False))
        self.assertIn("paused must be true", messages(check(paused_false)))

        still_paused = factory_package()
        replace_json(
            still_paused,
            "state.json",
            lambda obj: obj.update({"paused": False, "archived": True}),
        )
        self.assertIn("paused must be true", messages(check(still_paused)))

        missing = factory_package()
        del missing["packages/team-setup/v1/belts/issues/state.json"]
        self.assertIn("missing state.json", messages(check(missing)))

        for key, snippet in (("paused", "missing paused"), ("archived", "missing archived")):
            files = factory_package()
            replace_json(files, "state.json", lambda obj, key=key: obj.pop(key))
            self.assertIn(snippet, messages(check(files)))

        for key, value, snippet in (
            ("paused", "true", "paused has the wrong type"),
            ("archived", "false", "archived has the wrong type"),
        ):
            files = factory_package()
            replace_json(files, "state.json", lambda obj, key=key, value=value: obj.__setitem__(key, value))
            self.assertIn(snippet, messages(check(files)))

    def test_agent_flag_is_optional_and_only_archived(self) -> None:
        files = factory_package()
        files["packages/team-setup/v1/agents/scribe/state.json"] = dumps({"archived": True})
        self.assertEqual(check(files), [])
        files["packages/team-setup/v1/agents/scribe/state.json"] = dumps({"archived": False, "paused": True})
        self.assertIn("unknown keys paused", messages(check(files)))


class ReadmeTests(unittest.TestCase):
    def test_bounds_for_every_kind(self) -> None:
        exact = "é".encode() * (README_BYTES // 2)
        self.assertEqual(len(exact), 65536)
        over = exact + b"x"
        builders = {
            "belt": belt_package(),
            "agent": agent_package(),
            "factory": factory_package(),
        }
        for kind, files in builders.items():
            root = next(path for path in files if path.endswith("/package.json")).rsplit("/", 1)[0]
            with self.subTest(kind=kind, case="absent"):
                absent = dict(files)
                absent.pop(f"{root}/README.md", None)
                self.assertEqual(check(absent), [])
            with self.subTest(kind=kind, case="empty"):
                empty = dict(files)
                empty[f"{root}/README.md"] = b""
                self.assertEqual(check(empty), [])
            with self.subTest(kind=kind, case="exact"):
                bounded = dict(files)
                bounded[f"{root}/README.md"] = exact
                self.assertEqual(check(bounded), [])
            with self.subTest(kind=kind, case="over"):
                larger = dict(files)
                larger[f"{root}/README.md"] = over
                self.assertIn("README.md exceeds 65536 bytes", messages(check(larger)))
            with self.subTest(kind=kind, case="utf8"):
                broken = dict(files)
                broken[f"{root}/README.md"] = b"\xff"
                self.assertIn("README.md is not valid UTF-8", messages(check(broken)))


README_BYTES = 65536


class VersionTests(unittest.TestCase):
    def test_numbering_and_kind(self) -> None:
        first = belt_package("issue-flow", 1)
        second = belt_package("issue-flow", 2)
        third = belt_package("issue-flow", 3)
        fourth = belt_package("issue-flow", 4)
        fifth = belt_package("issue-flow", 5)
        self.assertEqual(check(first), [])
        self.assertEqual(check({**first, **second}, first), [])
        self.assertEqual(check({**first, **fourth, **fifth}, {**first, **fourth}), [])
        self.assertIn("next version must be v2", messages(check({**first, **third}, first)))
        self.assertIn("next version must be v5", messages(check({**first, **fourth, **second}, {**first, **fourth})))
        self.assertIn("next version must be v1", messages(check(second)))
        self.assertIn("at most one new version", messages(check({**first, **second})))
        two = {**belt_package("one"), **agent_package("two")}
        self.assertEqual(check(two), [])
        changed_kind = {**first, **agent_package("issue-flow", 2)}
        self.assertIn("kind must stay belt", messages(check(changed_kind, first)))

    def test_immutability_with_a_replacement_version(self) -> None:
        base = belt_package()
        edited = belt_package()
        replace_json(edited, "package.json", lambda obj: obj.__setitem__("summary", "Edited summary."))
        added = {**edited, **belt_package("issue-flow", 2)}
        self.assertIn("published file changed", messages(check(edited, base)))
        self.assertIn("published file changed", messages(check(added, base)))
        self.assertEqual(check({**base, **belt_package("issue-flow", 2)}, base), [])

        removed = dict(base)
        deleted = next(path for path in removed if path.endswith("README.md") or path.endswith(".md"))
        # The belt package has no README; delete the agent file from the published tree.
        deleted = "packages/issue-flow/v1/agents/triage/v1.md"
        removed.pop(deleted)
        self.assertIn("published file deleted", messages(check(removed, base)))

        renamed = dict(base)
        payload = renamed.pop(deleted)
        renamed["packages/issue-flow/v1/agents/triage/moved.md"] = payload
        found = messages(check(renamed, base))
        self.assertIn("published file deleted", found)
        self.assertIn("published file added", found)

        self.assertTrue(any("published file deleted" in message for message in messages(check({"packages/.gitkeep": b""}, base))))

        head = entries(base)
        target = "packages/issue-flow/v1/package.json"
        head[target] = check_packages.make_entry(base[target], mode="100755")
        self.assertIn("published file mode changed", messages(check_packages.evaluate(head, entries(base))))


class ResetTests(unittest.TestCase):
    """Issue #29's single reviewed catalog reset and its guards."""

    def snapshot(self) -> dict[str, bytes]:
        return {
            **belt_package("issue-flow"),
            **agent_package("review"),
            **factory_package("team-setup"),
        }

    @contextmanager
    def pinned(self, base: dict[str, bytes]):
        """Treat a synthetic catalog as the reviewed reset snapshot."""
        previous = check_packages.RESET_CATALOG_FINGERPRINT
        check_packages.RESET_CATALOG_FINGERPRINT = check_packages.catalog_fingerprint(entries(base))
        try:
            yield
        finally:
            check_packages.RESET_CATALOG_FINGERPRINT = previous

    def test_reviewed_snapshot_resets_to_gitkeep(self) -> None:
        base = self.snapshot()
        with self.pinned(base):
            found = check({"packages/.gitkeep": b""}, base)
        self.assertEqual(found, [])
        self.assertEqual(check_packages.exit_code(found), 0)

    def test_reset_ignores_changes_outside_packages(self) -> None:
        base = self.snapshot()
        with self.pinned(base):
            found = check({"packages/.gitkeep": b"", "README.md": b"changed\n"}, base)
        self.assertEqual(found, [])

    def test_empty_and_placeholder_only_transitions_pass(self) -> None:
        self.assertEqual(check({"packages/.gitkeep": b""}), [])
        self.assertEqual(check({"packages/.gitkeep": b""}, {"packages/.gitkeep": b""}), [])
        self.assertEqual(check({"packages/.gitkeep": b"\n"}, {"packages/.gitkeep": b""}), [])
        self.assertEqual(check({"packages/.gitkeep": b"", "docs.md": b"new\n"}, {"docs.md": b"old\n"}), [])

    def test_partial_removal_from_the_pinned_snapshot_fails(self) -> None:
        base = self.snapshot()
        head = {"packages/.gitkeep": b""}
        head.update({path: data for path, data in base.items() if not path.startswith("packages/issue-flow/")})
        with self.pinned(base):
            found = check(head, base)
        self.assertEqual(check_packages.exit_code(found), 1)
        self.assertIn("published file deleted", messages(found))

    def test_retaining_one_release_while_deleting_others_fails(self) -> None:
        base = self.snapshot()
        head = {"packages/.gitkeep": b""}
        head.update({path: data for path, data in base.items() if path.startswith("packages/review/v1/")})
        with self.pinned(base):
            found = check(head, base)
        self.assertEqual(check_packages.exit_code(found), 1)
        self.assertIn("published file deleted", messages(found))

    def test_removing_all_packages_from_a_different_snapshot_fails(self) -> None:
        pinned_base = self.snapshot()
        other_base = {path: data for path, data in pinned_base.items() if not path.startswith("packages/review/")}
        with self.pinned(pinned_base):
            found = check({"packages/.gitkeep": b""}, other_base)
        self.assertEqual(check_packages.exit_code(found), 1)
        self.assertIn("published file deleted", messages(found))

    def test_modified_base_before_full_removal_fails(self) -> None:
        original = self.snapshot()
        payload = "packages/review/v1/agents/review/v1.md"
        changed_bytes = dict(original)
        changed_bytes[payload] = b"changed\n"
        changed_path = {path: data for path, data in original.items() if path != payload}
        changed_path["packages/review/v1/agents/review/moved.md"] = original[payload]
        changed_mode = entries(original)
        changed_mode[payload] = check_packages.make_entry(original[payload], mode="100755")
        cases = {
            "bytes": entries(changed_bytes),
            "path": entries(changed_path),
            "mode": changed_mode,
        }
        for name, base in cases.items():
            with self.subTest(name=name):
                with self.pinned(original):
                    found = check_packages.evaluate({"packages/.gitkeep": check_packages.make_entry(b"")}, base)
                self.assertEqual(check_packages.exit_code(found), 1)
                self.assertIn("published file deleted", messages(found))

    def test_removal_combined_with_a_new_release_fails(self) -> None:
        base = self.snapshot()
        head = {"packages/.gitkeep": b"", **belt_package("fresh-belt")}
        with self.pinned(base):
            found = check(head, base)
        self.assertEqual(check_packages.exit_code(found), 1)
        self.assertIn("published file deleted", messages(found))

    def test_replaced_gitkeep_fails(self) -> None:
        base = self.snapshot()
        cases = {
            "symlink": check_packages.make_entry(None, "120000", "abc"),
            "executable": check_packages.make_entry(b"", mode="100755"),
            "nonempty": check_packages.make_entry(b"x"),
        }
        for name, entry in cases.items():
            with self.subTest(name=name):
                with self.pinned(base):
                    found = check_packages.evaluate({"packages/.gitkeep": entry}, entries(base))
                self.assertEqual(check_packages.exit_code(found), 1)
                self.assertIn("published file deleted", messages(found))
                if name == "symlink":
                    self.assertIn("symlink", messages(found))

    def test_unpinned_snapshot_removal_still_fails(self) -> None:
        base = self.snapshot()
        found = check({"packages/.gitkeep": b""}, base)
        self.assertEqual(check_packages.exit_code(found), 1)
        self.assertIn("published file deleted", messages(found))

    def test_catalog_fingerprint_ignores_outside_paths_and_entry_order(self) -> None:
        base = entries(self.snapshot())
        self.assertEqual(
            check_packages.catalog_fingerprint(base),
            check_packages.catalog_fingerprint(dict(reversed(list(base.items())))),
        )
        outside = {**base, "README.md": check_packages.make_entry(b"outside\n")}
        self.assertEqual(check_packages.catalog_fingerprint(base), check_packages.catalog_fingerprint(outside))


class WarningTests(unittest.TestCase):
    def test_warning_families_do_not_echo_the_value(self) -> None:
        sentinels = {
            "ghp_": "ghp_sentinelTokenValue123",
            "gho_": "gho_sentinelTokenValue123",
            "ghu_": "ghu_sentinelTokenValue123",
            "ghs_": "ghs_sentinelTokenValue123",
            "ghr_": "ghr_sentinelTokenValue123",
            "github_pat_": "github_pat_sentinelTokenValue123",
            "private key": "-----BEGIN OPENSSH PRIVATE KEY-----\nabc\n",
            "assignment": "password=sentinel-secret-value",
            "json assignment": '"secret": "sentinel-json-value"',
            "users": "/Users/sentinel-reviewer/notes",
            "home": "/home/sentinel-reviewer/notes",
            "windows": "C:\\Users\\sentinel-reviewer\\notes",
        }
        messages_for = {
            "ghp_": "Possible GitHub token",
            "gho_": "Possible GitHub token",
            "ghu_": "Possible GitHub token",
            "ghs_": "Possible GitHub token",
            "ghr_": "Possible GitHub token",
            "github_pat_": "Possible GitHub token",
            "private key": "Possible private key",
            "assignment": "Possible secret assignment",
            "json assignment": "Possible secret assignment",
            "users": "Possible personal path",
            "home": "Possible personal path",
            "windows": "Possible personal path",
        }
        for name, secret in sentinels.items():
            with self.subTest(name=name):
                files = belt_package("example")
                files["packages/example/v1/README.md"] = f"line\n{secret}\n".encode()
                found = check(files)
                self.assertEqual(messages(found), [])
                self.assertTrue(any(item.message.startswith(messages_for[name]) for item in found))
                output = rendered(found)
                self.assertNotIn(secret, output)
                self.assertNotIn("sentinel", output)
                self.assertEqual(check_packages.exit_code(found), 0)

    def test_personal_path_annotation_names_the_line(self) -> None:
        files = belt_package("example")
        files["packages/example/v1/README.md"] = b"one\ntwo\nthree\n/Users/hidden-person/notes\n"
        output = rendered(check(files))
        self.assertIn(
            "::warning file=packages/example/v1/README.md,line=4::Possible personal path; review before merging",
            output,
        )
        self.assertNotIn("hidden-person", output)

    def test_combined_warning_and_error_order(self) -> None:
        files = belt_package("example")
        files["packages/example/v1/README.md"] = b"one\ntwo\nthree\n/Users/hidden-person/notes\n"
        replace_json(files, "belts/issues/v1.json", lambda obj: obj.__setitem__("repos", ["synthetic/private-repo"]))
        found = check(files)
        self.assertEqual(
            [(item.severity, item.path, item.message) for item in found],
            [
                ("warning", "packages/example/v1/README.md", "Possible personal path; review before merging"),
                ("error", "packages/example/v1/belts/issues/v1.json", "repos must be []"),
            ],
        )
        self.assertEqual(check_packages.exit_code(found), 1)
        output = rendered(found)
        self.assertIn("::error file=packages/example/v1/belts/issues/v1.json", output)
        self.assertIn("repos must be []", output)
        self.assertNotIn("synthetic/private-repo", output)

    def test_private_repository_in_free_text_passes(self) -> None:
        files = belt_package(
            "example",
            label="owner/private-widget",
            brief="See owner/private-widget before starting.",
        )
        files["packages/example/v1/README.md"] = b"Mirrors owner/private-widget.\n"
        self.assertEqual(check(files), [])

    def test_blocking_diagnostics_do_not_reprint_secret_like_text(self) -> None:
        sentinels = [
            "ghp_12345678SECRET",
            "gho_12345678SECRET",
            "ghu_12345678SECRET",
            "ghs_12345678SECRET",
            "ghr_12345678SECRET",
            "github_pat_12345678SECRET",
            "-----BEGIN OPENSSH PRIVATE KEY-----\nsentinel-key-body\n",
            "password=sentinel-secret-value",
            "/Users/sentinel-reviewer/notes",
            "/home/sentinel-reviewer/notes",
            "C:\\Users\\sentinel-reviewer\\notes",
        ]
        for secret in sentinels:
            with self.subTest(secret=secret.split("\n", 1)[0][:24]):
                document = manifest("sample", "belt", "Sample", "Ships.")
                document["kind"] = secret
                files = belt_package("sample")
                files["packages/sample/v1/package.json"] = dumps(document)
                found = check(files)
                output = rendered(found)
                self.assertNotIn(secret, output)
                self.assertNotIn("sentinel", output)
                self.assertIn("unknown kind", output)
                self.assertIn("[redacted]", output)
                self.assertTrue(any(item.severity == "warning" for item in found))
                self.assertEqual(check_packages.exit_code(found), 1)
                for line in output.splitlines():
                    for _category, pattern, _message in check_packages.WARNINGS:
                        self.assertIsNone(pattern.search(line))

        document = manifest("sample", "belt", "Sample", "Ships.")
        document["ghp_12345678SECRET"] = True
        files = belt_package("sample")
        files["packages/sample/v1/package.json"] = dumps(document)
        output = rendered(check(files))
        self.assertNotIn("ghp_12345678SECRET", output)
        self.assertIn("unknown keys", output)
        self.assertIn("[redacted]", output)
        for line in output.splitlines():
            for _category, pattern, _message in check_packages.WARNINGS:
                self.assertIsNone(pattern.search(line))

    def test_assignment_values_are_fully_redacted(self) -> None:
        value = "sentinel-secret-value"
        tail = "entinel"
        forms = {
            "password=": f"password={value}",
            'password=""': f'password="{value}"',
            "token:": f"token:{value}",
            'token:""': f'token:"{value}"',
            "secret = ": f"secret = {value}",
            'secret = ""': f'secret = "{value}"',
        }
        for name, secret in forms.items():
            with self.subTest(name=name):
                direct = check_packages.redact_sensitive(f'unknown key "{secret}"')
                self.assertNotIn(value, direct)
                self.assertNotIn(tail, direct)
                self.assertIn("[redacted]", direct)

                document = manifest("sample", "belt", "Sample", "Ships.")
                document["kind"] = secret
                files = belt_package("sample")
                files["packages/sample/v1/package.json"] = dumps(document)
                found = check(files)
                output = rendered(found)
                self.assertNotIn(value, output)
                self.assertNotIn(tail, output)
                self.assertIn("unknown kind", output)
                self.assertIn("[redacted]", output)
                self.assertTrue(any(item.severity == "warning" for item in found))
                self.assertEqual(check_packages.exit_code(found), 1)
                for line in output.splitlines():
                    for _category, pattern, _message in check_packages.WARNINGS:
                        self.assertIsNone(pattern.search(line))

                repo = Repo(self)
                repo.write("packages/.gitkeep", b"")
                base = repo.commit("placeholder")
                payload = {
                    "schemaVersion": 1,
                    "id": "sample",
                    "name": "Sample",
                    "kind": secret,
                    "summary": "Ships.",
                    "author": "octocat",
                    "tags": [],
                }
                repo.write(
                    "packages/sample/v1/package.json",
                    (json.dumps(payload, separators=(",", ":")) + "\n").encode(),
                )
                repo.commit("secret assignment")
                result = run_check(repo, base)
                self.assertNotEqual(result.returncode, 0)
                self.assertNotIn(value, result.stdout)
                self.assertNotIn(value, result.stderr)
                self.assertNotIn(tail, result.stdout)
                self.assertNotIn(tail, result.stderr)
                self.assertIn("[redacted]", result.stdout)
                self.assertIn("unknown kind", result.stdout)

        spaced = "sentinel secret value"
        quoted_space = f'password="{spaced}"'
        redacted_space = check_packages.redact_sensitive(f'unknown key "{quoted_space}"')
        self.assertNotIn("sentinel", redacted_space)
        self.assertNotIn("entinel", redacted_space)
        self.assertNotIn("secret value", redacted_space)
        self.assertIn("[redacted]", redacted_space)

    def test_secret_tails_stay_out_of_annotations_and_cli_output(self) -> None:
        marker = "SECRET-TAIL"
        cases = {
            "password=": f"password=x{marker}",
            'password=""': f'password="x{marker}"',
            "token:": f"token:x{marker}",
            'token:""': f'token:"x{marker}"',
            "secret = ": f"secret = x{marker}",
            'secret = ""': f'secret = "x{marker}"',
            "quoted space": f'password="x {marker}"',
            "escaped quote": 'password="x\\"' + marker + '"',
            "single quoted embedded double": f"password='x\"{marker}'",
            "hyphenated token": f"ghp_12345678-{marker}",
            "punctuated token": f"github_pat_12345678.{marker}",
        }
        for name, secret in cases.items():
            with self.subTest(name=name):
                direct = check_packages.redact_sensitive(f'unknown kind "{secret}"')
                self.assert_secret_tail_hidden(direct, secret)
                self.assertIn("[redacted]", direct)
                self.assertIn("unknown kind", direct)

                document = manifest("sample", "belt", "Sample", "Ships.")
                document["kind"] = secret
                files = belt_package("sample")
                files["packages/sample/v1/package.json"] = dumps(document)
                found = check(files)
                output = rendered(found)
                self.assert_secret_tail_hidden(output, secret)
                self.assertIn("unknown kind", output)
                self.assertIn("[redacted]", output)
                self.assertTrue(any(item.severity == "warning" for item in found))
                self.assertEqual(check_packages.exit_code(found), 1)
                for line in output.splitlines():
                    for _category, pattern, _message in check_packages.WARNINGS:
                        self.assertIsNone(pattern.search(line))

                repo = Repo(self)
                repo.write("packages/.gitkeep", b"")
                base = repo.commit("placeholder")
                payload = {
                    "schemaVersion": 1,
                    "id": "sample",
                    "name": "Sample",
                    "kind": secret,
                    "summary": "Ships.",
                    "author": "octocat",
                    "tags": [],
                }
                repo.write(
                    "packages/sample/v1/package.json",
                    (json.dumps(payload, separators=(",", ":")) + "\n").encode(),
                )
                repo.commit("secret tail")
                result = run_check(repo, base)
                self.assertNotEqual(result.returncode, 0)
                self.assert_secret_tail_hidden(result.stdout, secret)
                self.assert_secret_tail_hidden(result.stderr, secret)
                self.assertIn("[redacted]", result.stdout)
                self.assertIn("unknown kind", result.stdout)

    def assert_secret_tail_hidden(self, text: str, secret: str) -> None:
        """No fragment of the secret value after its first character may remain."""
        self.assertNotIn("SECRET-TAIL", text)
        for index in range(1, len(secret)):
            fragment = secret[index:]
            if len(fragment) < 8:
                continue
            self.assertNotIn(fragment, text)

    def test_unknown_kind_secret_is_redacted_on_the_cli(self) -> None:
        secret = "ghp_12345678SECRET"
        repo = Repo(self)
        repo.write("packages/.gitkeep", b"")
        base = repo.commit("placeholder")
        document = {
            "schemaVersion": 1,
            "id": "sample",
            "name": "Sample",
            "kind": secret,
            "summary": "Ships.",
            "author": "octocat",
            "tags": [],
        }
        repo.write(
            "packages/sample/v1/package.json",
            (json.dumps(document, separators=(",", ":")) + "\n").encode(),
        )
        repo.commit("secret kind")
        result = run_check(repo, base)
        self.assertNotEqual(result.returncode, 0)
        combined = result.stdout + result.stderr
        self.assertNotIn(secret, combined)
        self.assertIn(
            '::error file=packages/sample/v1/package.json,line=1::unknown kind "[redacted]',
            result.stdout,
        )
        self.assertNotIn("2345678SECRET", result.stdout)
        self.assertNotIn("2345678SECRET", result.stderr)
        self.assertIn(
            "::warning file=packages/sample/v1/package.json,line=1::Possible GitHub token; review before merging",
            result.stdout,
        )
        error_at = result.stdout.index("::error")
        warning_at = result.stdout.index("::warning")
        self.assertLess(error_at, warning_at)

    def test_annotation_escaping(self) -> None:
        document = manifest("widget", "belt", "Widget", "Ships.")
        document["kind"] = "wei%\nrd"
        document["a:b"] = 1
        document["c,d"] = 1
        files = belt_package("widget")
        files["packages/widget/v1/package.json"] = dumps(document)
        output = rendered(check(files))
        path_files = belt_package("widget")
        path_files["packages/widget/v1/README%.md"] = b"nope\n"
        path_files["packages/widget/v1/a,b.txt"] = b"nope\n"
        output += "\n" + rendered(check(path_files))
        kind_line = next(line for line in output.splitlines() if "unknown kind" in line)
        self.assertIn("%25", kind_line)
        self.assertIn("%0A", kind_line)
        self.assertNotIn("%250A", kind_line)
        self.assertNotIn("wei%\n", output)
        message = kind_line.split("::")[-1]
        self.assertNotIn("%3A", message)
        self.assertTrue(any(line.split("::")[-1] == "unknown keys a:b, c,d" or "a:b" in line.split("::")[-1] for line in output.splitlines()))
        self.assertIn("README%25.md", output)
        self.assertNotIn("README%.md", output)
        self.assertIn("a%2Cb.txt", output)
        self.assertNotIn("a,b.txt", output)


class DocsTests(unittest.TestCase):
    def test_contributing_and_readme(self) -> None:
        contributing = (ROOT / "CONTRIBUTING.md").read_text(encoding="utf-8")
        readme = (ROOT / "README.md").read_text(encoding="utf-8")
        self.assertIn("python3 scripts/check_packages.py --base origin/main", contributing)
        self.assertIn("python3 -m unittest discover -s tests -v", contributing)
        self.assertIn("Reviewers must check free text for private repository references.", contributing)
        self.assertIn("immutable", contributing.lower())
        self.assertIn("warning", contributing.lower())
        self.assertIn("Every factory belt requires state.json with paused:true and a boolean archived.", readme)
        self.assertIn("Agent state.json remains optional and may contain only a boolean archived.", readme)
        self.assertIn("## Catalog reset", readme)
        self.assertIn("Issue [#29]", readme)
        self.assertIn("intentionally cleared the current catalog", readme)
        self.assertIn("previously imported local factory", readme)
        self.assertIn("did not delete Git history", readme)
        self.assertIn("not part of the current catalog", readme)
        self.assertIn("packages/.gitkeep", readme)
        self.assertIn("single reviewed exception", readme)
        self.assertIn("catalog reset", contributing)
        self.assertIn("issue #29", contributing)
        self.assertIn("does not delete Git history", contributing)
        self.assertIn("does not remove anyone's imported local copies", contributing)
        self.assertIn("packages/.gitkeep", contributing)
        self.assertIn("partial removals of the reset snapshot", contributing)

    def test_workflow_contract(self) -> None:
        text = (ROOT / ".github/workflows/check-packages.yml").read_text(encoding="utf-8")
        self.assertNotIn("pull_request_target", text)
        self.assertIn("pull_request:", text)
        self.assertIn("push:", text)
        self.assertIn("branches: [main]", text)
        self.assertIn("check-packages:", text)
        self.assertIn("python3 -m unittest discover -s tests -v", text)
        self.assertIn("python3 scripts/check_packages.py --base", text)
        self.assertIn("contents: read", text)
        self.assertIn("fetch-depth: 0", text)
        self.assertNotIn("paths:", text)


class GitHistoryTests(unittest.TestCase):
    def test_cli_accepts_valid_packages_and_rejects_malformed_and_missing_bases(self) -> None:
        repo = Repo(self)
        repo.write("packages/.gitkeep", b"")
        base = repo.commit("placeholder")
        repo.write_tree(belt_package())
        repo.write_tree(agent_package())
        repo.write_tree(factory_package())
        head = repo.commit("packages")
        passed = run_check(repo, base, head)
        self.assertEqual(passed.returncode, 0, passed.stdout + passed.stderr)
        self.assertEqual(passed.stdout, "")

        broken = Repo(self)
        broken.write("packages/.gitkeep", b"")
        broken_base = broken.commit("placeholder")
        broken.write("packages/example/v1/package.json", b"{")
        broken.commit("malformed")
        failed = run_check(broken, broken_base)
        self.assertNotEqual(failed.returncode, 0)
        self.assertIn("invalid JSON", failed.stdout)

        missing = run_check(repo, "1111111111111111111111111111111111111111", head)
        self.assertNotEqual(missing.returncode, 0)
        self.assertIn("missing or unreadable", missing.stdout)

        first = Repo(self)
        first.write_tree(belt_package())
        first.commit("first")
        empty_base = run_check(first, ZERO)
        self.assertEqual(empty_base.returncode, 0, empty_base.stdout + empty_base.stderr)

        omitted = subprocess.run([sys.executable, str(SCRIPT)], cwd=repo.path, capture_output=True, text=True)
        self.assertNotEqual(omitted.returncode, 0)

    def test_published_versions_are_immutable(self) -> None:
        repo = Repo(self)
        repo.write_tree(belt_package())
        repo.write("packages/issue-flow/v1/README.md", b"Original.\n")
        base = repo.commit("v1")

        edited = clone_from(self, repo, base)
        edited.write("packages/issue-flow/v1/README.md", b"Edited.\n")
        edited.commit("edit")
        self.assertIn("published file changed", run_check(edited, base).stdout)

        deleted = clone_from(self, repo, base)
        (Path(deleted.path) / "packages/issue-flow/v1/README.md").unlink()
        deleted.commit("delete")
        self.assertIn("published file deleted", run_check(deleted, base).stdout)

        renamed = clone_from(self, repo, base)
        readme = Path(renamed.path) / "packages/issue-flow/v1/README.md"
        readme.rename(readme.with_name("NOTES.md"))
        renamed.commit("rename")
        renamed_out = run_check(renamed, base).stdout
        self.assertIn("published file deleted", renamed_out)
        self.assertIn("published file added", renamed_out)

        removed = clone_from(self, repo, base)
        shutil.rmtree(Path(removed.path) / "packages/issue-flow")
        removed.write("packages/.gitkeep", b"\n")
        removed.commit("remove package")
        self.assertIn("published file deleted", run_check(removed, base).stdout)

        mode = clone_from(self, repo, base)
        mode.git("update-index", "--chmod=+x", "--", "packages/issue-flow/v1/README.md")
        mode.git("commit", "-m", "mode")
        self.assertIn("published file mode changed", run_check(mode, base).stdout)

        added = clone_from(self, repo, base)
        added.write_tree(belt_package("issue-flow", 2))
        added.commit("v2")
        passed = run_check(added, base)
        self.assertEqual(passed.returncode, 0, passed.stdout + passed.stderr)

        both = clone_from(self, repo, base)
        both.write("packages/issue-flow/v1/README.md", b"Edited.\n")
        both.write_tree(belt_package("issue-flow", 2))
        both.commit("edit and v2")
        self.assertNotEqual(run_check(both, base).returncode, 0)

    def test_git_modes_are_not_followed(self) -> None:
        repo = Repo(self)
        repo.write("packages/.gitkeep", b"")
        base = repo.commit("placeholder")
        link = Path(repo.path) / "packages/example/v1/package.json"
        link.parent.mkdir(parents=True)
        link.symlink_to("missing-target")
        repo.commit("symlink")
        failed = run_check(repo, base)
        self.assertNotEqual(failed.returncode, 0)
        self.assertIn("symlink", failed.stdout)
        self.assertNotIn("invalid JSON", failed.stdout)
        self.assertNotIn("Traceback", failed.stderr)

        linked = Repo(self)
        linked.write("packages/.gitkeep", b"")
        parent = linked.commit("placeholder")
        sha = parent
        linked.git("update-index", "--add", "--cacheinfo", f"160000,{sha},packages/example/v1/nested")
        linked.git("commit", "-m", "gitlink")
        gitlink = run_check(linked, parent)
        self.assertNotEqual(gitlink.returncode, 0)
        self.assertIn("submodule", gitlink.stdout)
        self.assertNotIn("Traceback", gitlink.stderr)

    def test_push_before_sha_sees_every_commit_in_the_push(self) -> None:
        repo = Repo(self)
        repo.write("packages/.gitkeep", b"")
        repo.commit("placeholder")
        repo.write_tree(belt_package())
        repo.write("packages/issue-flow/v1/README.md", b"One.\n")
        before = repo.commit("v1")
        repo.write("packages/issue-flow/v1/README.md", b"Two.\n")
        parent = repo.commit("edit")
        repo.write_tree(belt_package("issue-flow", 2))
        after = repo.commit("v2")
        cumulative = run_check(repo, before, after)
        self.assertNotEqual(cumulative.returncode, 0)
        self.assertIn("published file changed", cumulative.stdout)
        stepwise = run_check(repo, parent, after)
        self.assertEqual(stepwise.returncode, 0, stepwise.stdout + stepwise.stderr)

    def test_placeholder_only_change_passes(self) -> None:
        repo = Repo(self)
        repo.write("packages/.gitkeep", b"")
        base = repo.commit("keep")
        repo.write("packages/.gitkeep", b"\n")
        repo.commit("touch keep")
        result = run_check(repo, base)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)


class ResetGitTests(unittest.TestCase):
    """CLI coverage for issue #29's reviewed catalog reset."""

    def snapshot_repo(self) -> tuple[Repo, str]:
        repo = Repo(self)
        repo.write_tree(baseline_snapshot(self))
        return repo, repo.commit("baseline catalog")

    def clear_catalog(self, repo: Repo) -> None:
        shutil.rmtree(Path(repo.path) / "packages")
        repo.write("packages/.gitkeep", b"")

    def test_pinned_fingerprint_matches_the_baseline_catalog(self) -> None:
        snapshot = baseline_snapshot(self)
        loaded = check_packages.load_tree(ROOT, BASELINE_COMMIT)
        self.assertEqual(check_packages.catalog_fingerprint(loaded), check_packages.RESET_CATALOG_FINGERPRINT)
        tree = subprocess.run(
            ["git", "-C", str(ROOT), "rev-parse", f"{BASELINE_COMMIT}:packages"],
            capture_output=True,
            text=True,
            check=True,
        )
        self.assertEqual(tree.stdout.strip(), BASELINE_PACKAGES_TREE)
        self.assertEqual(snapshot["packages/.gitkeep"], b"")
        self.assertGreater(len(snapshot), 1)

    def test_exact_snapshot_to_gitkeep_passes_through_the_cli(self) -> None:
        repo, base = self.snapshot_repo()
        self.clear_catalog(repo)
        head = repo.commit("clear catalog")
        result = run_check(repo, base, head)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual(result.stdout, "")

    def test_empty_to_empty_and_placeholder_only_pass_through_the_cli(self) -> None:
        repo = Repo(self)
        repo.write("packages/.gitkeep", b"")
        base = repo.commit("empty catalog")
        same = run_check(repo, base, base)
        self.assertEqual(same.returncode, 0, same.stdout + same.stderr)
        first_commit = run_check(repo, ZERO, base)
        self.assertEqual(first_commit.returncode, 0, first_commit.stdout + first_commit.stderr)
        repo.write("packages/.gitkeep", b"\n")
        head = repo.commit("placeholder only")
        changed = run_check(repo, base, head)
        self.assertEqual(changed.returncode, 0, changed.stdout + changed.stderr)

    def assert_blocked(self, repo: Repo, base: str, head: str, snippet: str = "published file deleted") -> None:
        result = run_check(repo, base, head)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn(snippet, result.stdout)

    def test_removing_one_package_from_the_snapshot_fails(self) -> None:
        repo, base = self.snapshot_repo()
        shutil.rmtree(Path(repo.path) / "packages" / "starter-factory")
        self.assert_blocked(repo, base, repo.commit("remove one package"))

    def test_retaining_one_release_while_deleting_others_fails(self) -> None:
        repo, base = self.snapshot_repo()
        packages = Path(repo.path) / "packages"
        for child in list(packages.iterdir()):
            if child.name in {".gitkeep", "triage"}:
                continue
            if child.is_dir():
                shutil.rmtree(child)
            else:
                child.unlink()
        self.assert_blocked(repo, base, repo.commit("keep one release"))

    def test_removing_a_different_snapshot_fails(self) -> None:
        repo = Repo(self)
        snapshot = baseline_snapshot(self)
        altered = {path: data for path, data in snapshot.items() if not path.startswith("packages/review/")}
        repo.write_tree(altered)
        base = repo.commit("different snapshot")
        self.clear_catalog(repo)
        self.assert_blocked(repo, base, repo.commit("remove other snapshot"))

    def test_modified_base_before_full_removal_fails(self) -> None:
        payload = "packages/review/v1/agents/review/v1.md"
        cases = {
            "bytes": lambda snapshot: {**snapshot, payload: b"changed\n"},
            "path": lambda snapshot: {
                **{path: data for path, data in snapshot.items() if path != payload},
                "packages/review/v1/agents/review/moved.md": snapshot[payload],
            },
        }
        for name, mutate in cases.items():
            with self.subTest(name=name):
                repo = Repo(self)
                repo.write_tree(mutate(baseline_snapshot(self)))
                base = repo.commit("modified base")
                self.clear_catalog(repo)
                self.assert_blocked(repo, base, repo.commit("remove modified base"))

        repo = Repo(self)
        repo.write_tree(baseline_snapshot(self))
        os.chmod(Path(repo.path) / "packages" / "review" / "v1" / "agents" / "review" / "v1.md", 0o755)
        base = repo.commit("executable base")
        self.clear_catalog(repo)
        self.assert_blocked(repo, base, repo.commit("remove executable base"), "published file deleted")

    def test_removal_combined_with_a_new_release_fails(self) -> None:
        repo, base = self.snapshot_repo()
        self.clear_catalog(repo)
        repo.write_tree(belt_package("fresh-belt"))
        self.assert_blocked(repo, base, repo.commit("clear and publish"))

    def test_replaced_gitkeep_fails(self) -> None:
        def replace_with_symlink(repo: Repo) -> None:
            path = Path(repo.path) / "packages" / ".gitkeep"
            path.unlink()
            path.symlink_to("missing-target")

        def replace_with_executable(repo: Repo) -> None:
            os.chmod(Path(repo.path) / "packages" / ".gitkeep", 0o755)

        def replace_with_content(repo: Repo) -> None:
            repo.write("packages/.gitkeep", b"x")

        cases = {
            "symlink": replace_with_symlink,
            "executable": replace_with_executable,
            "nonempty": replace_with_content,
        }
        for name, replace in cases.items():
            with self.subTest(name=name):
                repo, base = self.snapshot_repo()
                self.clear_catalog(repo)
                replace(repo)
                head = repo.commit(f"replaced gitkeep ({name})")
                result = run_check(repo, base, head)
                self.assertNotEqual(result.returncode, 0)
                self.assertIn("published file deleted", result.stdout)
                if name == "symlink":
                    self.assertIn("symlink", result.stdout)


class PublishAfterResetTests(unittest.TestCase):
    """Publishing from the cleared catalog keeps the normal safeguards."""

    def empty_repo(self) -> tuple[Repo, str]:
        repo = Repo(self)
        repo.write("packages/.gitkeep", b"")
        return repo, repo.commit("empty catalog")

    def test_v1_then_v2_from_the_empty_catalog_pass(self) -> None:
        repo, base = self.empty_repo()
        repo.write_tree(belt_package("fresh-belt"))
        v1 = repo.commit("v1")
        first = run_check(repo, base, v1)
        self.assertEqual(first.returncode, 0, first.stdout + first.stderr)
        repo.write_tree(belt_package("fresh-belt", 2))
        v2 = repo.commit("v2")
        second = run_check(repo, v1, v2)
        self.assertEqual(second.returncode, 0, second.stdout + second.stderr)

    def test_first_version_must_be_v1(self) -> None:
        repo, base = self.empty_repo()
        repo.write_tree(belt_package("fresh-belt", 2))
        result = run_check(repo, base, repo.commit("v2 first"))
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("next version must be v1", result.stdout)

    def test_skipping_a_version_fails(self) -> None:
        repo, base = self.empty_repo()
        repo.write_tree(belt_package("fresh-belt", 1))
        v1 = repo.commit("v1")
        repo.write_tree(belt_package("fresh-belt", 3))
        result = run_check(repo, v1, repo.commit("v3"))
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("next version must be v2", result.stdout)

    def test_changing_kind_fails(self) -> None:
        repo, base = self.empty_repo()
        repo.write_tree(belt_package("fresh-belt", 1))
        v1 = repo.commit("v1")
        repo.write_tree(agent_package("fresh-belt", 2))
        result = run_check(repo, v1, repo.commit("v2 agent"))
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("kind must stay belt", result.stdout)

    def test_mutating_published_v1_fails(self) -> None:
        repo, base = self.empty_repo()
        repo.write_tree(belt_package("fresh-belt", 1))
        v1 = repo.commit("v1")
        files = belt_package("fresh-belt")
        replace_json(files, "package.json", lambda obj: obj.__setitem__("summary", "Edited summary."))
        repo.write_tree(files)
        result = run_check(repo, v1, repo.commit("edit v1"))
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("published file changed", result.stdout)

    def test_invalid_layout_from_the_empty_catalog_fails(self) -> None:
        repo, base = self.empty_repo()
        files = belt_package("fresh-belt")
        files["packages/fresh-belt/v1/agents/extra/v1.md"] = agent_markdown("extra", 1)
        repo.write_tree(files)
        result = run_check(repo, base, repo.commit("unpinned agent"))
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("not pinned by the belt", result.stdout)


def load_fixture(name: str) -> dict[str, bytes]:
    root = ROOT / "tests" / "fixtures" / name
    files = {}
    for path in root.rglob("*"):
        if path.is_file():
            files[path.relative_to(root).as_posix()] = path.read_bytes()
    return files


class Repo:
    def __init__(self, test: unittest.TestCase):
        self.tmp = tempfile.TemporaryDirectory()
        test.addCleanup(self.tmp.cleanup)
        self.path = self.tmp.name
        self.git("init", "-b", "main")

    def git(self, *args: str, check: bool = True) -> subprocess.CompletedProcess[str]:
        result = subprocess.run(
            [
                "git",
                "-C",
                self.path,
                "-c",
                "user.email=checker@example.com",
                "-c",
                "user.name=Checker",
                "-c",
                "commit.gpgsign=false",
                "-c",
                "core.autocrlf=false",
                *args,
            ],
            capture_output=True,
            text=True,
        )
        if check and result.returncode != 0:
            raise AssertionError(f"git {args} failed\n{result.stderr}")
        return result

    def write(self, rel: str, data: bytes) -> None:
        path = Path(self.path) / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)

    def write_tree(self, files: dict[str, bytes]) -> None:
        for rel, data in files.items():
            self.write(rel, data)

    def commit(self, message: str) -> str:
        self.git("add", "-A")
        self.git("commit", "-m", message)
        return self.rev()

    def rev(self, ref: str = "HEAD") -> str:
        return self.git("rev-parse", ref).stdout.strip()


def clone_from(test: unittest.TestCase, source: Repo, commit: str) -> Repo:
    copy = Repo(test)
    copy.git("remote", "add", "source", source.path)
    copy.git("fetch", "--no-tags", "source", "+refs/heads/main:refs/remotes/source/main")
    copy.git("checkout", "-B", "main", commit)
    return copy


def run_check(repo: Repo, base: str, head: str = "HEAD") -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(SCRIPT), "--base", base, "--head", head],
        cwd=repo.path,
        capture_output=True,
        text=True,
    )


def baseline_snapshot(test: unittest.TestCase) -> dict[str, bytes]:
    """Load the reviewed issue #29 catalog from this repository's history."""
    probe = subprocess.run(
        ["git", "-C", str(ROOT), "cat-file", "-e", f"{BASELINE_COMMIT}^{{commit}}"],
        capture_output=True,
    )
    if probe.returncode != 0:
        test.skipTest("baseline catalog commit is not available in this checkout")
    loaded = check_packages.load_tree(ROOT, BASELINE_COMMIT)
    return {
        path: entry.content
        for path, entry in loaded.items()
        if path.startswith("packages/") and entry.content is not None
    }


if __name__ == "__main__":
    unittest.main()
