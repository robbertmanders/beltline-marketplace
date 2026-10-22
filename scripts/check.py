#!/usr/bin/env python3
"""Checks this repository's belts and agents against the rules in CONTRIBUTING.md.

Every file under belts/ and agents/ must be belts/<id>/v<n>.json or
agents/<id>/v<n>.md. A belt's id and version match its path, it carries no
repositories, base branch, repository bases or origin, and every agent version
its stages pin is here. An agent has frontmatter and no origin. With --base, a
version that exists on the base revision must not be changed or removed.

It only reads files and runs `git diff`; it never runs what it reads.
"""

import argparse
import json
import re
import subprocess
import sys
from pathlib import Path

ID = r"[A-Za-z0-9_-]+"
BELT_PATH = re.compile(rf"^belts/({ID})/v([1-9][0-9]*)\.json$")
AGENT_PATH = re.compile(rf"^agents/({ID})/v([1-9][0-9]*)\.md$")


def library_files(root):
    """The paths under belts/ and agents/, relative to root, sorted."""
    files = []
    for kind in ("belts", "agents"):
        folder = root / kind
        if folder.is_dir():
            files += [p.relative_to(root).as_posix() for p in folder.rglob("*") if p.is_file()]
    return sorted(files)


def frontmatter(text):
    """The agent file's frontmatter lines, or None when it has none."""
    lines = text.splitlines()
    if not lines or lines[0].strip() != "---":
        return None
    for index, line in enumerate(lines[1:], start=1):
        if line.strip() == "---":
            return lines[1:index]
    return None


def check_belt(path, ident, version, text, problems):
    """Adds the belt's problems and returns the agent versions it pins."""
    try:
        belt = json.loads(text)
    except json.JSONDecodeError as error:
        problems.append(f"{path}: not valid JSON ({error.msg})")
        return []
    if not isinstance(belt, dict):
        problems.append(f"{path}: not a JSON object")
        return []
    if belt.get("id") != ident or belt.get("version") != version:
        problems.append(f"{path}: its id and version must match the path")
    for index, trigger in enumerate(belt.get("triggers") or []):
        if isinstance(trigger, dict) and trigger.get("repos"):
            problems.append(f"{path}: trigger {index + 1} lists repositories; shared belts leave `repos` empty")
    if belt.get("base"):
        problems.append(f"{path}: `base` must be empty")
    for key in ("repositoryBases", "origin"):
        if key in belt:
            problems.append(f"{path}: remove `{key}`")
    pins = []
    for stage in belt.get("stages") or []:
        agent = stage.get("agent") if isinstance(stage, dict) else None
        if isinstance(agent, dict):
            pins.append((agent.get("id"), agent.get("version")))
    return pins


def check_agent(path, text, problems):
    lines = frontmatter(text)
    if lines is None:
        problems.append(f"{path}: an agent file starts with frontmatter between `---` lines")
        return
    for line in lines:
        key = line.split(":", 1)[0].strip()
        if key in ("origin", "originPath"):
            problems.append(f"{path}: remove `{key}` from the frontmatter")


def check_tree(root):
    """The problems with the belts and agents under root."""
    problems = []
    agents = set()
    pins = []
    for path in library_files(root):
        text = (root / path).read_text(encoding="utf-8", errors="replace")
        if match := BELT_PATH.match(path):
            ident, version = match.group(1), int(match.group(2))
            pins += [(path, pin) for pin in check_belt(path, ident, version, text, problems)]
        elif match := AGENT_PATH.match(path):
            agents.add((match.group(1), int(match.group(2))))
            check_agent(path, text, problems)
        else:
            problems.append(f"{path}: expected belts/<id>/v<n>.json or agents/<id>/v<n>.md")
    for path, (ident, version) in pins:
        if (ident, version) not in agents:
            problems.append(f"{path}: pins agent {ident} v{version}, which is not in agents/")
    return problems


def check_published(root, base):
    """The problems with versions on base that were changed, removed or renamed."""
    output = subprocess.run(
        ["git", "diff", "--name-status", "--no-renames", f"{base}...HEAD", "--", "belts", "agents"],
        cwd=root, check=True, capture_output=True, text=True,
    ).stdout
    problems = []
    for line in output.splitlines():
        status, _, path = line.partition("\t")
        if status != "A" and (BELT_PATH.match(path) or AGENT_PATH.match(path)):
            problems.append(f"{path}: a published version never changes; add the next version instead")
    return problems


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--base", help="the revision whose versions must stay unchanged, such as origin/main")
    parser.add_argument("--root", default=".", help="the repository to check (default: here)")
    args = parser.parse_args(argv)
    root = Path(args.root).resolve()
    problems = check_tree(root)
    if args.base:
        problems += check_published(root, args.base)
    for problem in problems:
        print(problem)
    if problems:
        return 1
    print(f"{len(library_files(root))} files checked, no problems.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
