#!/usr/bin/env python3
"""Check Beltline marketplace packages between two Git commits.

Python 3 and the standard library only. Reads Git trees and blobs, so it
does not follow symlinks or execute package contents.

    python3 scripts/check_packages.py --base origin/main
    python3 scripts/check_packages.py --base <commit> [--head <commit>]

The all-zero base SHA is an empty tree, used for a repository's first commit.
Any other missing or unreadable commit fails the check.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

ZERO = "0" * 40
REGULAR_MODES = {"100644", "100755"}
KINDS = {"factory", "belt", "agent"}
TRIGGER_KINDS = {"issues", "reviews", "jira", "schedule", "manual"}
LEGACY_AGENTS = {"triage", "spec", "build", "verify", "review", "custom"}
STAGE_TYPES = {"agent", "approve", "watch"} | LEGACY_AGENTS
TONES = {"good", "you", "problem", "neutral"}
ACTIONS = {"next", "goto", "route", "retry", "hold", "park", "done", "drop"}
WORKSPACES = {"readOnly", "worktree", "worktreeReadOnly"}
RUNNERS = {"copilot", "pi", "claude", "codex", "cursor"}
THINKING = {"low", "medium", "high", "xhigh", "max"}
MACHINES = {
    "sorter", "typewriter", "mailbox", "robot", "microscope", "reader", "van", "box",
    "telescope", "stamp", "crane", "drill", "radar",
}
TINTS = {"blue", "sand", "gold", "green", "violet", "rose", "teal", "coral", "grey"}
README_LIMIT = 65536

MANIFEST_KEYS = ["schemaVersion", "id", "name", "kind", "summary", "author", "tags"]
FACTORY_KEYS = ["schemaVersion", "id", "name"]

GITHUB_TOKEN = re.compile(r"(?:ghp_|gho_|ghu_|ghs_|ghr_|github_pat_)[A-Za-z0-9_]{8,}")
PRIVATE_KEY = re.compile(r"-----BEGIN (?:[A-Z0-9]+ )?PRIVATE KEY-----")
# One non-space character is enough to warn. Redaction hides more than that.
SECRET_ASSIGNMENT = re.compile(r'(?i)(?:"|\b)(?:token|password|secret)(?:"|\b)[ \t]*[=:][ \t]*\S')
PERSONAL_PATH = re.compile(r"(?:/Users/|/home/|[A-Za-z]:[\\/]+Users[\\/])")
# From the assignment keyword through the end of the diagnostic. A quoted value
# can contain an escaped quote; keeping the rest of the message is not worth a leak.
ASSIGNMENT_REDACTION = re.compile(
    r'(?i)(?:"|\b)(?:token|password|secret)(?:"|\b)[ \t]*[=:][\s\S]*'
)
# Through the end of the non-whitespace token, so a hyphen or other punctuation
# after the recognised prefix cannot survive.
GITHUB_TOKEN_REDACTION = re.compile(
    r"(?:ghp_|gho_|ghu_|ghs_|ghr_|github_pat_)[A-Za-z0-9_]{8,}\S*"
)

WARNINGS = (
    ("github-token", GITHUB_TOKEN, "Possible GitHub token; review before merging"),
    ("private-key", PRIVATE_KEY, "Possible private key; review before merging"),
    ("secret-assignment", SECRET_ASSIGNMENT, "Possible secret assignment; review before merging"),
    ("personal-path", PERSONAL_PATH, "Possible personal path; review before merging"),
)

# Wider than the warning detectors. An assignment or a private-key header drops
# the rest of the diagnostic. A token prefix drops the rest of that non-whitespace
# token. A personal path drops the rest of that non-space token.
REDACTIONS = (
    GITHUB_TOKEN_REDACTION,
    re.compile(r"-----BEGIN (?:[A-Z0-9]+ )?PRIVATE KEY-----[\s\S]*"),
    ASSIGNMENT_REDACTION,
    re.compile(r"(?:/Users/|/home/|[A-Za-z]:[\\/]+Users[\\/])\S*"),
)


class GitFailure(Exception):
    pass


@dataclass(frozen=True)
class Entry:
    mode: str
    sha: str
    content: bytes | None


@dataclass(frozen=True)
class Diagnostic:
    path: str
    line: int
    severity: str
    message: str


def blob_sha(content: bytes) -> str:
    header = f"blob {len(content)}\0".encode("ascii")
    return hashlib.sha1(header + content).hexdigest()


def make_entry(content: bytes | None, mode: str = "100644", sha: str | None = None) -> Entry:
    if sha is None:
        if content is None:
            raise ValueError("sha is required when content is absent")
        sha = blob_sha(content)
    return Entry(mode, sha, content)


def sort_key(diagnostic: Diagnostic) -> tuple:
    return (diagnostic.path, diagnostic.line, diagnostic.severity, diagnostic.message)


def sort_unique(diagnostics: list[Diagnostic]) -> list[Diagnostic]:
    ordered = sorted(diagnostics, key=sort_key)
    unique: list[Diagnostic] = []
    seen: set[tuple] = set()
    for diagnostic in ordered:
        key = (diagnostic.path, diagnostic.line, diagnostic.severity, diagnostic.message)
        if key in seen:
            continue
        seen.add(key)
        unique.append(diagnostic)
    return unique


def escape_data(value: str) -> str:
    return value.replace("%", "%25").replace("\r", "%0D").replace("\n", "%0A")


def redact_sensitive(text: str) -> str:
    """Replace secret-like spans so a diagnostic cannot reprint a matched value."""
    for pattern in REDACTIONS:
        text = pattern.sub("[redacted]", text)
    return text


def escape_property(value: str) -> str:
    return escape_data(value).replace(":", "%3A").replace(",", "%2C")


def format_annotation(diagnostic: Diagnostic) -> str:
    message = escape_data(redact_sensitive(diagnostic.message))
    if not diagnostic.path:
        return f"::{diagnostic.severity}::{message}"
    props = f"file={escape_property(diagnostic.path)}"
    if diagnostic.line:
        props += f",line={diagnostic.line}"
    return f"::{diagnostic.severity} {props}::{message}"


def exit_code(diagnostics: list[Diagnostic]) -> int:
    return 1 if any(item.severity == "error" for item in diagnostics) else 0


def is_int(value: object) -> bool:
    return type(value) is int


def is_blank(value: str) -> bool:
    return value.strip() == ""


def safe_id(value: str) -> bool:
    if not value or value in {".", ".."}:
        return False
    return all(character.isascii() and (character.isalnum() or character in "-_") for character in value)


def canonical_version_name(name: str) -> int | None:
    if re.fullmatch(r"v[1-9][0-9]*", name):
        return int(name[1:])
    return None


def looks_like_version(name: str) -> bool:
    return len(name) > 1 and name[0] == "v" and name[1].isdigit()


def is_unsafe(path: str) -> bool:
    if "\\" in path or path.startswith("/"):
        return True
    return any(part in {"", ".", ".."} for part in path.split("/"))


def release_prefix(path: str) -> str | None:
    if not path.startswith("packages/"):
        return None
    parts = path.split("/")
    if len(parts) < 4:
        return None
    return "/".join(parts[:3])


def mode_problem(mode: str) -> str | None:
    if mode in REGULAR_MODES:
        return None
    if mode == "120000":
        return "symlink"
    if mode == "160000":
        return "submodule"
    return "unsupported file mode"


def json_key_line(text: str, key: str, depth: int = 1) -> int:
    """Return the 1-based line of an object key at a brace/bracket depth."""
    target = f'"{key}"'
    index = 0
    current = 0
    length = len(text)
    while index < length:
        character = text[index]
        if character == '"':
            end = index + 1
            escaped = False
            while end < length:
                if escaped:
                    escaped = False
                elif text[end] == "\\":
                    escaped = True
                elif text[end] == '"':
                    break
                end += 1
            if current == depth and text.startswith(target, index) and end == index + len(target) - 1:
                cursor = end + 1
                while cursor < length and text[cursor] in " \t\r\n":
                    cursor += 1
                if cursor < length and text[cursor] == ":":
                    return text.count("\n", 0, index) + 1
            index = end + 1
            continue
        if character in "{[":
            current += 1
        elif character in "}]":
            current -= 1
        index += 1
    return 0


def decode_json(content: bytes) -> tuple[object | None, str | None, str | None]:
    try:
        text = content.decode("utf-8")
    except UnicodeDecodeError:
        return None, None, "invalid UTF-8"
    try:
        return json.loads(text), text, None
    except json.JSONDecodeError:
        return None, text, "invalid JSON"


def add(diagnostics: list[Diagnostic], path: str, line: int, message: str, severity: str = "error") -> None:
    diagnostics.append(Diagnostic(path, line, severity, message))


def scan_warnings(path: str, content: bytes, diagnostics: list[Diagnostic]) -> None:
    try:
        text = content.decode("utf-8")
    except UnicodeDecodeError:
        return
    seen: set[tuple[str, int]] = set()
    for category, pattern, message in WARNINGS:
        for match in pattern.finditer(text):
            line = text.count("\n", 0, match.start()) + 1
            key = (category, line)
            if key in seen:
                continue
            seen.add(key)
            add(diagnostics, path, line, message, "warning")


def git(root: Path, args: list[str], check: bool = True) -> subprocess.CompletedProcess[bytes]:
    result = subprocess.run(["git", "-C", str(root), *args], capture_output=True)
    if check and result.returncode != 0:
        raise GitFailure(f"git {' '.join(args)} failed")
    return result


def git_root(cwd: Path) -> Path:
    result = subprocess.run(
        ["git", "-C", str(cwd), "rev-parse", "--show-toplevel"],
        capture_output=True,
    )
    if result.returncode != 0:
        raise GitFailure("not a git repository")
    return Path(result.stdout.decode().strip())


def resolve_commit(root: Path, rev: str) -> str | None:
    if rev == ZERO:
        return ZERO
    result = git(root, ["rev-parse", "--verify", "--end-of-options", f"{rev}^{{commit}}"], check=False)
    if result.returncode != 0:
        return None
    return result.stdout.decode().strip()


def load_tree(root: Path, commit: str) -> dict[str, Entry]:
    if commit == ZERO:
        return {}
    listing = git(root, ["ls-tree", "-r", "-z", commit]).stdout
    entries: dict[str, Entry] = {}
    for record in listing.split(b"\0"):
        if not record:
            continue
        meta, path_bytes = record.split(b"\t", 1)
        mode, _kind, sha = meta.decode("ascii").split(" ")
        path = path_bytes.decode("utf-8", "surrogateescape")
        content = None
        if mode in REGULAR_MODES:
            content = git(root, ["cat-file", "blob", sha]).stdout
        entries[path] = Entry(mode, sha, content)
    return entries


def load_commit(root: Path, rev: str, label: str) -> tuple[dict[str, Entry] | None, Diagnostic | None]:
    if rev == ZERO:
        return {}, None
    commit = resolve_commit(root, rev)
    if commit is None:
        return None, Diagnostic("", 0, "error", f"{label} commit {rev} is missing or unreadable")
    return load_tree(root, commit), None


def paths_under(entries: dict[str, Entry], prefix: str) -> dict[str, Entry]:
    needle = prefix + "/"
    return {path: entry for path, entry in entries.items() if path.startswith(needle)}


def immutability(head: dict[str, Entry], base: dict[str, Entry]) -> list[Diagnostic]:
    diagnostics: list[Diagnostic] = []
    prefixes = {release_prefix(path) for path in base}
    prefixes.discard(None)
    for prefix in sorted(prefixes):
        assert prefix is not None
        before = paths_under(base, prefix)
        after = paths_under(head, prefix)
        for path in sorted(set(before) - set(after)):
            add(diagnostics, path, 0, "published file deleted")
        for path in sorted(set(after) - set(before)):
            add(diagnostics, path, 0, "published file added")
        for path in sorted(set(before) & set(after)):
            old = before[path]
            new = after[path]
            if old.sha != new.sha:
                add(diagnostics, path, 0, "published file changed")
            elif old.mode != new.mode:
                add(diagnostics, path, 0, "published file mode changed")
    return diagnostics


def versions_by_package(entries: dict[str, Entry]) -> dict[str, set[int]]:
    found: dict[str, set[int]] = {}
    seen: set[str] = set()
    for path in entries:
        prefix = release_prefix(path)
        if prefix is None or prefix in seen:
            continue
        seen.add(prefix)
        _packages, package_id, version_name = prefix.split("/")
        number = canonical_version_name(version_name)
        if number is None:
            continue
        found.setdefault(package_id, set()).add(number)
    return found


def peek_kind(entry: Entry | None) -> str | None:
    if entry is None or entry.content is None:
        return None
    value, _text, error = decode_json(entry.content)
    if error or not isinstance(value, dict):
        return None
    kind = value.get("kind")
    return kind if isinstance(kind, str) else None


def kind_of(entries: dict[str, Entry], package_id: str, number: int) -> str | None:
    path = f"packages/{package_id}/v{number}/package.json"
    return peek_kind(entries.get(path))


def numbering_and_kind(head: dict[str, Entry], base: dict[str, Entry]) -> list[Diagnostic]:
    diagnostics: list[Diagnostic] = []
    head_versions = versions_by_package(head)
    base_versions = versions_by_package(base)
    for package_id in sorted(set(head_versions) | set(base_versions)):
        old = base_versions.get(package_id, set())
        new = head_versions.get(package_id, set()) - old
        if len(new) > 1:
            add(diagnostics, f"packages/{package_id}", 0, "at most one new version")
        elif len(new) == 1:
            expected = 1 if not old else max(old) + 1
            got = next(iter(new))
            if got != expected:
                add(diagnostics, f"packages/{package_id}", 0, f"next version must be v{expected}")
        if not new or not old:
            continue
        published = [(number, kind_of(base, package_id, number)) for number in old]
        published_kinds = [kind for _number, kind in published if kind]
        if not published_kinds:
            continue
        base_kind = kind_of(base, package_id, max(old)) or published_kinds[-1]
        for number in sorted(new):
            new_kind = kind_of(head, package_id, number)
            if new_kind and new_kind != base_kind:
                add(
                    diagnostics,
                    f"packages/{package_id}/v{number}/package.json",
                    0,
                    f"kind must stay {base_kind}",
                )
    return diagnostics


def definition_version(filename: str, suffix: str) -> int | None:
    if not filename.endswith(suffix):
        return None
    return canonical_version_name(filename[: -len(suffix)])


def check_string_field(
    diagnostics: list[Diagnostic],
    path: str,
    text: str,
    obj: dict,
    key: str,
    *,
    single_line: bool = False,
) -> str | None:
    if key not in obj:
        add(diagnostics, path, 0, f"missing {key}")
        return None
    value = obj[key]
    line = json_key_line(text, key)
    if value is None:
        add(diagnostics, path, line, f"null {key}")
        return None
    if not isinstance(value, str):
        add(diagnostics, path, line, f"{key} has the wrong type")
        return None
    if is_blank(value):
        add(diagnostics, path, line, f"empty {key}")
        return None
    if single_line and ("\n" in value or "\r" in value):
        add(diagnostics, path, line, "summary must be a single line")
        return None
    return value


def inspect_manifest(
    diagnostics: list[Diagnostic], path: str, content: bytes, package_id: str
) -> dict | None:
    value, text, error = decode_json(content)
    if error:
        add(diagnostics, path, 0, error)
        return None
    if not isinstance(value, dict) or text is None:
        add(diagnostics, path, 0, "manifest must be an object")
        return None
    unknown = sorted(set(value) - set(MANIFEST_KEYS))
    if unknown:
        add(diagnostics, path, json_key_line(text, unknown[0]), f"unknown keys {', '.join(unknown)}")
    if "schemaVersion" not in value:
        add(diagnostics, path, 0, "missing schemaVersion")
    else:
        schema = value["schemaVersion"]
        line = json_key_line(text, "schemaVersion")
        if schema is None:
            add(diagnostics, path, line, "null schemaVersion")
        elif not is_int(schema):
            add(diagnostics, path, line, "schemaVersion has the wrong type")
        elif schema != 1:
            add(diagnostics, path, line, f"unsupported schemaVersion {schema}")
    identifier = None
    if "id" not in value:
        add(diagnostics, path, 0, "missing id")
    else:
        raw_id = value["id"]
        line = json_key_line(text, "id")
        if raw_id is None:
            add(diagnostics, path, line, "null id")
        elif not isinstance(raw_id, str):
            add(diagnostics, path, line, "id has the wrong type")
        else:
            identifier = raw_id
            if not safe_id(raw_id):
                add(diagnostics, path, line, "invalid id")
            if raw_id != package_id:
                add(diagnostics, path, line, "id does not match package directory")
    name = check_string_field(diagnostics, path, text, value, "name")
    check_string_field(diagnostics, path, text, value, "summary", single_line=True)
    check_string_field(diagnostics, path, text, value, "author")
    kind = None
    if "kind" not in value:
        add(diagnostics, path, 0, "missing kind")
    else:
        raw_kind = value["kind"]
        line = json_key_line(text, "kind")
        if raw_kind is None:
            add(diagnostics, path, line, "null kind")
        elif not isinstance(raw_kind, str):
            add(diagnostics, path, line, "kind has the wrong type")
        elif raw_kind not in KINDS:
            add(diagnostics, path, line, f'unknown kind "{raw_kind}"')
        else:
            kind = raw_kind
    if "tags" not in value:
        add(diagnostics, path, 0, "missing tags")
    else:
        tags = value["tags"]
        line = json_key_line(text, "tags")
        if tags is None:
            add(diagnostics, path, line, "null tags")
        elif not isinstance(tags, list):
            add(diagnostics, path, line, "tags has the wrong type")
        else:
            for index, item in enumerate(tags):
                if not isinstance(item, str):
                    add(diagnostics, path, line, f"tags[{index}] has the wrong type")
                elif is_blank(item):
                    add(diagnostics, path, line, f"tags[{index}] is blank")
    return {"id": identifier, "name": name, "kind": kind}


def check_readme(diagnostics: list[Diagnostic], path: str, content: bytes) -> None:
    if len(content) > README_LIMIT:
        add(diagnostics, path, 0, f"README.md exceeds {README_LIMIT} bytes")
    try:
        content.decode("utf-8")
    except UnicodeDecodeError:
        add(diagnostics, path, 0, "README.md is not valid UTF-8")


def unquote_scalar(value: str) -> str:
    value = value.strip()
    if len(value) >= 2 and value[0] == value[-1] and value[0] in {'"', "'"}:
        inner = value[1:-1]
        if value[0] == "'":
            return inner.replace("''", "'")
        result = []
        escaped = False
        for character in inner:
            if escaped:
                result.append("\n" if character == "n" else character)
                escaped = False
            elif character == "\\":
                escaped = True
            else:
                result.append(character)
        return "".join(result)
    if " #" in value:
        value = value.split(" #", 1)[0].rstrip()
    return value


def parse_agent(text: str, agent_id: str, version: int) -> list[tuple[int, str]]:
    problems: list[tuple[int, str]] = []
    lines = text.split("\n")
    if not lines or lines[0].strip() != "---":
        return [(1, "malformed frontmatter")]
    end = None
    for index, line in enumerate(lines[1:], start=1):
        if line.strip() == "---":
            end = index
            break
    if end is None:
        return [(1, "malformed frontmatter")]
    for index, line in enumerate(lines[1:end], start=2):
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        if line[:1] in " \t":
            continue
        if ":" not in line:
            continue
        key, raw_value = line.split(":", 1)
        key = key.strip()
        value = raw_value.strip().strip("\"'")
        if key == "id" and value != agent_id:
            problems.append((index, "id/version disagrees with path"))
        if key == "version":
            try:
                parsed = int(value.strip())
            except ValueError:
                problems.append((index, "id/version disagrees with path"))
            else:
                if parsed != version:
                    problems.append((index, "id/version disagrees with path"))
    in_outcomes = False
    outcomes: list[dict[str, str]] = []
    for index, line in enumerate(lines[1:end], start=2):
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        indented = line[:1] in " \t"
        if not indented:
            if ":" not in line:
                problems.append((index, "malformed frontmatter"))
                continue
            key, raw_value = line.split(":", 1)
            key = key.strip()
            value = unquote_scalar(raw_value)
            in_outcomes = key == "outcomes"
            if key == "workspace" and value not in WORKSPACES:
                problems.append((index, "invalid workspace"))
            elif key == "runner" and value not in RUNNERS:
                problems.append((index, "invalid runner"))
            elif key == "thinking" and value not in THINKING:
                problems.append((index, "invalid thinking"))
            elif key == "machine" and value not in MACHINES:
                problems.append((index, "invalid machine"))
            elif key == "tint" and value not in TINTS:
                problems.append((index, "invalid tint"))
            elif key == "slots":
                try:
                    int(value)
                except ValueError:
                    problems.append((index, "invalid slots"))
            continue
        if not in_outcomes:
            problems.append((index, "malformed frontmatter"))
            continue
        if stripped.startswith("-"):
            outcomes.append({})
            rest = stripped[1:].strip()
            if not rest:
                continue
            if ":" not in rest:
                problems.append((index, "malformed frontmatter"))
                continue
            key, raw_value = rest.split(":", 1)
            outcomes[-1][key.strip()] = unquote_scalar(raw_value)
            continue
        if not outcomes:
            problems.append((index, "malformed frontmatter"))
            continue
        if ":" not in stripped:
            problems.append((index, "malformed frontmatter"))
            continue
        key, raw_value = stripped.split(":", 1)
        outcomes[-1][key.strip()] = unquote_scalar(raw_value)
    for outcome in outcomes:
        if not outcome.get("name", "").strip():
            problems.append((end, "malformed frontmatter"))
        tone = outcome.get("tone")
        if tone is not None and tone not in TONES:
            problems.append((end, "invalid tone"))
        action = outcome.get("then")
        if action is not None and action not in ACTIONS:
            problems.append((end, "invalid then"))
        for flag in ("withOutput", "comment"):
            if flag in outcome and outcome[flag].lower() not in {"true", "false", "yes", "no"}:
                problems.append((end, f"invalid {flag}"))
        if "max" in outcome:
            try:
                int(outcome["max"])
            except ValueError:
                problems.append((end, "invalid max"))
    return problems


def outcome_ok(item: object) -> bool:
    if not isinstance(item, dict):
        return False
    if not all(isinstance(item.get(key), str) and not is_blank(item[key]) for key in ("id", "name", "when")):
        return False
    if item.get("tone") not in TONES:
        return False
    then = item.get("then")
    if not isinstance(then, dict) or then.get("do") not in ACTIONS:
        return False
    return True


def check_belt_object(
    diagnostics: list[Diagnostic], path: str, obj: dict, text: str, belt_id: str, version: int
) -> list[tuple[str, int]]:
    pins: list[tuple[str, int]] = []
    if "id" not in obj:
        add(diagnostics, path, 0, "missing id")
    elif not isinstance(obj["id"], str):
        add(diagnostics, path, json_key_line(text, "id"), "id has the wrong type")
    elif obj["id"] != belt_id:
        add(diagnostics, path, json_key_line(text, "id"), "id/version disagrees with path")
    if "name" not in obj:
        add(diagnostics, path, 0, "missing name")
    elif not isinstance(obj["name"], str):
        add(diagnostics, path, json_key_line(text, "name"), "name has the wrong type")
    if "version" not in obj:
        add(diagnostics, path, 0, "missing version")
    elif not is_int(obj["version"]):
        add(diagnostics, path, json_key_line(text, "version"), "version has the wrong type")
    elif obj["version"] != version:
        add(diagnostics, path, json_key_line(text, "version"), "id/version disagrees with path")
    if "repos" not in obj or obj["repos"] != []:
        add(diagnostics, path, json_key_line(text, "repos"), "repos must be []")
    if "base" not in obj or obj["base"] != "":
        add(diagnostics, path, json_key_line(text, "base"), 'base must be ""')
    if "afkEnabled" not in obj or obj["afkEnabled"] is not False:
        add(diagnostics, path, json_key_line(text, "afkEnabled"), "afkEnabled must be false")
    trigger = obj.get("trigger", None)
    if "trigger" not in obj:
        add(diagnostics, path, 0, "missing trigger")
    elif not isinstance(trigger, dict):
        add(diagnostics, path, json_key_line(text, "trigger"), "trigger has the wrong type")
    else:
        kind = trigger.get("kind", "issues")
        if not isinstance(kind, str) or kind not in TRIGGER_KINDS:
            add(diagnostics, path, json_key_line(text, "trigger"), "malformed trigger")
        if "repos" in trigger and trigger["repos"] != []:
            add(diagnostics, path, json_key_line(text, "repos", depth=2), "trigger repos must be absent or []")
        if "base" in trigger and trigger["base"] != "":
            add(diagnostics, path, json_key_line(text, "base", depth=2), 'trigger base must be absent or ""')
    stages = obj.get("stages", None)
    if "stages" not in obj:
        add(diagnostics, path, 0, "missing stages")
        return pins
    if not isinstance(stages, list):
        add(diagnostics, path, json_key_line(text, "stages"), "stages has the wrong type")
        return pins
    for index, stage in enumerate(stages):
        if not isinstance(stage, dict):
            add(diagnostics, path, 0, "malformed stage")
            continue
        stage_id = stage.get("id")
        label = stage_id if isinstance(stage_id, str) and stage_id else str(index)
        stage_type = stage.get("type")
        if (
            not isinstance(stage_id, str)
            or not isinstance(stage.get("name"), str)
            or not isinstance(stage_type, str)
            or stage_type not in STAGE_TYPES
            or not isinstance(stage.get("outcomes"), list)
            or any(not outcome_ok(item) for item in stage["outcomes"])
        ):
            add(diagnostics, path, 0, "malformed stage")
            continue
        if "brief" in stage and not isinstance(stage["brief"], str):
            add(diagnostics, path, 0, "malformed stage")
        if stage_type == "agent":
            ref = stage.get("agent")
            agent_version = ref.get("version") if isinstance(ref, dict) else None
            if (
                not isinstance(ref, dict)
                or not isinstance(ref.get("id"), str)
                or not safe_id(ref["id"])
                or not is_int(agent_version)
                or agent_version <= 0
            ):
                add(diagnostics, path, 0, f"stage {label} has no agent pin")
            else:
                pins.append((ref["id"], agent_version))
        elif stage_type in LEGACY_AGENTS:
            pins.append((stage_type, 1))
    return pins


def check_flag(
    diagnostics: list[Diagnostic], path: str, content: bytes, *, belt: bool
) -> None:
    value, text, error = decode_json(content)
    if error:
        add(diagnostics, path, 0, error)
        return
    if not isinstance(value, dict) or text is None:
        add(diagnostics, path, 0, "flag must be an object")
        return
    allowed = {"paused", "archived"} if belt else {"archived"}
    unknown = sorted(set(value) - allowed)
    if unknown:
        add(diagnostics, path, json_key_line(text, unknown[0]), f"unknown keys {', '.join(unknown)}")
    if belt:
        if "paused" not in value:
            add(diagnostics, path, 0, "missing paused")
        else:
            paused = value["paused"]
            line = json_key_line(text, "paused")
            if type(paused) is not bool:
                add(diagnostics, path, line, "paused has the wrong type")
            elif paused is not True:
                add(diagnostics, path, line, "paused must be true")
    if "archived" not in value:
        add(diagnostics, path, 0, "missing archived")
    else:
        archived = value["archived"]
        line = json_key_line(text, "archived")
        if type(archived) is not bool:
            add(diagnostics, path, line, "archived has the wrong type")


def check_factory_manifest(
    diagnostics: list[Diagnostic],
    path: str,
    content: bytes,
    package_id: str,
    package_name: str | None,
) -> None:
    value, text, error = decode_json(content)
    if error:
        add(diagnostics, path, 0, error)
        return
    if not isinstance(value, dict) or text is None:
        add(diagnostics, path, 0, "factory manifest must be an object")
        return
    unknown = sorted(set(value) - set(FACTORY_KEYS))
    if unknown:
        add(diagnostics, path, json_key_line(text, unknown[0]), f"unknown keys {', '.join(unknown)}")
    if "schemaVersion" not in value:
        add(diagnostics, path, 0, "missing schemaVersion")
    else:
        schema = value["schemaVersion"]
        line = json_key_line(text, "schemaVersion")
        if schema is None:
            add(diagnostics, path, line, "null schemaVersion")
        elif not is_int(schema):
            add(diagnostics, path, line, "schemaVersion has the wrong type")
        elif schema != 1:
            add(diagnostics, path, line, f"unsupported schemaVersion {schema}")
    if "id" not in value:
        add(diagnostics, path, 0, "missing id")
    else:
        raw_id = value["id"]
        line = json_key_line(text, "id")
        if raw_id is None:
            add(diagnostics, path, line, "null id")
        elif not isinstance(raw_id, str):
            add(diagnostics, path, line, "id has the wrong type")
        else:
            if not safe_id(raw_id):
                add(diagnostics, path, line, "invalid id")
            if raw_id != package_id:
                add(diagnostics, path, line, "id does not match package id")
    if "name" not in value:
        add(diagnostics, path, 0, "missing name")
    else:
        raw_name = value["name"]
        line = json_key_line(text, "name")
        if raw_name is None:
            add(diagnostics, path, line, "null name")
        elif not isinstance(raw_name, str):
            add(diagnostics, path, line, "name has the wrong type")
        elif is_blank(raw_name):
            add(diagnostics, path, line, "empty name")
        elif package_name is not None and raw_name != package_name:
            add(diagnostics, path, line, "name does not match package name")


def check_release(
    diagnostics: list[Diagnostic], prefix: str, package_id: str, files: dict[str, Entry]
) -> None:
    manifest_entry = files.get("package.json")
    manifest = None
    if manifest_entry is None or manifest_entry.mode not in REGULAR_MODES or manifest_entry.content is None:
        if manifest_entry is None:
            add(diagnostics, f"{prefix}/package.json", 0, "missing manifest")
    else:
        manifest = inspect_manifest(diagnostics, f"{prefix}/package.json", manifest_entry.content, package_id)
    readme = files.get("README.md")
    if readme is not None and readme.mode in REGULAR_MODES and readme.content is not None:
        check_readme(diagnostics, f"{prefix}/README.md", readme.content)
    kind = manifest.get("kind") if manifest else None
    package_name = manifest.get("name") if manifest else None
    if kind not in KINDS:
        return
    if kind == "factory" and (
        "factory.json" not in files or files["factory.json"].mode not in REGULAR_MODES or files["factory.json"].content is None
    ):
        add(diagnostics, f"{prefix}/factory.json", 0, "missing manifest")

    belt_files: list[tuple[str, int, str]] = []
    agent_files: list[tuple[str, int, str]] = []
    belt_flags: dict[str, str] = {}
    agent_flags: dict[str, str] = {}
    pin_map: dict[str, list[tuple[str, int]]] = {}
    for rel, entry in sorted(files.items()):
        if entry.mode not in REGULAR_MODES or entry.content is None:
            continue
        full = f"{prefix}/{rel}"
        if rel in {"package.json", "README.md"}:
            continue
        parts = rel.split("/")
        if rel == "factory.json":
            if kind != "factory":
                add(diagnostics, full, 0, f"not part of a {kind} package")
            else:
                check_factory_manifest(diagnostics, full, entry.content, package_id, package_name)
            continue
        if len(parts) != 3 or parts[0] not in {"belts", "agents"} or not safe_id(parts[1]):
            add(diagnostics, full, 0, "unsupported path")
            continue
        root, ident, filename = parts
        if filename == "state.json":
            if kind != "factory":
                add(diagnostics, full, 0, "flag files belong only in a factory package")
            elif root == "belts":
                belt_flags[ident] = full
                check_flag(diagnostics, full, entry.content, belt=True)
            else:
                agent_flags[ident] = full
                check_flag(diagnostics, full, entry.content, belt=False)
            continue
        suffix = ".json" if root == "belts" else ".md"
        if looks_like_version(filename[: -len(suffix)] if filename.endswith(suffix) else filename):
            number = definition_version(filename, suffix)
            if number is None:
                add(diagnostics, full, 0, "invalid version number")
                continue
        else:
            number = definition_version(filename, suffix)
        if number is None:
            add(diagnostics, full, 0, "unsupported path")
            continue
        if root == "belts":
            if kind == "agent":
                add(diagnostics, full, 0, "not part of an agent package")
            belt_files.append((ident, number, full))
            value, text, error = decode_json(entry.content)
            if error or text is None:
                add(diagnostics, full, 0, error or "invalid JSON")
            elif not isinstance(value, dict):
                add(diagnostics, full, 0, "belt must be an object")
            else:
                pin_map[full] = check_belt_object(diagnostics, full, value, text, ident, number)
        else:
            agent_files.append((ident, number, full))
            try:
                agent_text = entry.content.decode("utf-8")
            except UnicodeDecodeError:
                add(diagnostics, full, 0, "invalid UTF-8")
            else:
                for line, message in parse_agent(agent_text, ident, number):
                    add(diagnostics, full, line, message)

    if kind == "factory" and not agent_files:
        add(diagnostics, f"{prefix}/agents", 0, "archive must contain at least one agent version")
    if kind == "belt":
        paths = [item[2] for item in belt_files]
        if len(belt_files) != 1:
            found = "none" if not paths else ", ".join(paths)
            add(diagnostics, f"{prefix}/package.json", 0, f"expected exactly one belt, found {found}")
    if kind == "agent":
        paths = [item[2] for item in agent_files]
        if len(agent_files) != 1:
            found = "none" if not paths else ", ".join(paths)
            add(diagnostics, f"{prefix}/package.json", 0, f"expected exactly one agent, found {found}")

    present_agents = {(ident, number) for ident, number, _path in agent_files}
    belt_ids = {ident for ident, _number, _path in belt_files}
    agent_ids = {ident for ident, _number, _path in agent_files}
    if kind == "factory":
        for ident in sorted(belt_ids):
            if ident not in belt_flags:
                add(diagnostics, f"{prefix}/belts/{ident}/state.json", 0, "missing state.json")
        for ident, path in sorted(belt_flags.items()):
            if ident not in belt_ids:
                add(diagnostics, path, 0, "flag does not belong to an included belt")
        for ident, path in sorted(agent_flags.items()):
            if ident not in agent_ids:
                add(diagnostics, path, 0, "flag does not belong to an included agent")
    for _ident, _number, full in belt_files:
        for agent_id, agent_version in pin_map.get(full, []):
            if (agent_id, agent_version) not in present_agents:
                add(diagnostics, full, 0, f"missing agents/{agent_id}/v{agent_version}.md")
    if kind == "belt" and len(belt_files) == 1:
        full = belt_files[0][2]
        pinned = set(pin_map.get(full, []))
        if full in pin_map:
            for ident, number, agent_path in agent_files:
                if (ident, number) not in pinned:
                    add(diagnostics, agent_path, 0, "not pinned by the belt")


def structure(entries: dict[str, Entry]) -> list[Diagnostic]:
    diagnostics: list[Diagnostic] = []
    groups: dict[str, dict[str, Entry]] = {}
    loose: list[str] = []
    for path, entry in sorted(entries.items()):
        if not path.startswith("packages/"):
            continue
        problem = mode_problem(entry.mode)
        if problem and path != "packages/.gitkeep":
            add(diagnostics, path, 0, problem)
        elif path == "packages/.gitkeep" and problem:
            add(diagnostics, path, 0, problem)
        if path == "packages/.gitkeep":
            continue
        if is_unsafe(path):
            add(diagnostics, path, 0, "unsafe path")
            continue
        if entry.mode in REGULAR_MODES and entry.content is not None:
            scan_warnings(path, entry.content, diagnostics)
        prefix = release_prefix(path)
        if prefix is None:
            if entry.mode in REGULAR_MODES:
                loose.append(path)
            continue
        rel = path[len(prefix) + 1 :]
        groups.setdefault(prefix, {})[rel] = entry
    for path in loose:
        add(diagnostics, path, 0, "unsupported path")
    for prefix, files in sorted(groups.items()):
        _packages, package_id, version_name = prefix.split("/")
        if not safe_id(package_id):
            add(diagnostics, prefix, 0, "invalid package id")
            continue
        if canonical_version_name(version_name) is None:
            if looks_like_version(version_name):
                add(diagnostics, prefix, 0, "invalid version number")
            else:
                for rel, entry in sorted(files.items()):
                    if entry.mode in REGULAR_MODES:
                        add(diagnostics, f"{prefix}/{rel}", 0, "unsupported path")
            continue
        check_release(diagnostics, prefix, package_id, files)
    return diagnostics


def evaluate(head: dict[str, Entry], base: dict[str, Entry]) -> list[Diagnostic]:
    diagnostics: list[Diagnostic] = []
    diagnostics.extend(immutability(head, base))
    diagnostics.extend(structure(head))
    diagnostics.extend(numbering_and_kind(head, base))
    return sort_unique(diagnostics)


def check_repository(cwd: Path, base: str, head: str) -> int:
    root = git_root(cwd)
    diagnostics: list[Diagnostic] = []
    head_entries, head_error = load_commit(root, head, "head")
    base_entries, base_error = load_commit(root, base, "base")
    if head_error:
        diagnostics.append(head_error)
    if base_error:
        diagnostics.append(base_error)
    if head_entries is not None and base_entries is not None:
        diagnostics.extend(evaluate(head_entries, base_entries))
    diagnostics = sort_unique(diagnostics)
    for diagnostic in diagnostics:
        print(format_annotation(diagnostic))
    return exit_code(diagnostics)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Check Beltline marketplace packages.")
    parser.add_argument("--base", required=True, help="comparison commit; 40 zeros means an empty tree")
    parser.add_argument("--head", default="HEAD", help="commit to validate (default: HEAD)")
    args = parser.parse_args(argv)
    try:
        return check_repository(Path.cwd(), args.base, args.head)
    except GitFailure as exc:
        print(f"::error::{escape_data(redact_sensitive(str(exc)))}")
        return 1


if __name__ == "__main__":
    sys.exit(main())
