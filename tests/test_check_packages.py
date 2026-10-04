"""Checker coverage for marketplace package proposals."""

from __future__ import annotations

import json
import shutil
import subprocess
import sys
import tempfile
import unittest
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


if __name__ == "__main__":
    unittest.main()
