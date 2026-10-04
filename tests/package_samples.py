"""Valid package payloads shared by the checker tests and on-disk fixtures."""

from __future__ import annotations

import json


def dumps(value: object) -> bytes:
    return (json.dumps(value, indent=2, sort_keys=True) + "\n").encode("utf-8")


def manifest(package_id: str, kind: str, name: str, summary: str, tags: list[str] | None = None) -> dict:
    return {
        "schemaVersion": 1,
        "id": package_id,
        "name": name,
        "kind": kind,
        "summary": summary,
        "author": "octocat",
        "tags": [] if tags is None else tags,
    }


def outcome(name: str = "done", when: str = "The work is finished.") -> dict:
    return {
        "id": name,
        "name": name,
        "when": when,
        "tone": "good",
        "then": {"do": "next"},
    }


def stage(stage_id: str, agent_id: str, version: int, brief: str = "Do the work.") -> dict:
    return {
        "id": stage_id,
        "type": "agent",
        "name": stage_id,
        "agent": {"id": agent_id, "version": version},
        "brief": brief,
        "outcomes": [outcome()],
    }


def belt(
    belt_id: str = "issues",
    version: int = 1,
    pins: list[tuple[str, int]] | None = None,
    label: str = "agent",
    brief: str = "Do the work.",
) -> dict:
    pins = pins if pins is not None else [("triage", 1)]
    return {
        "id": belt_id,
        "name": "Issues",
        "version": version,
        "trigger": {"kind": "issues", "label": label, "assignee": "anyone", "poll": 60},
        "repos": [],
        "base": "",
        "afkEnabled": False,
        "stages": [
            stage(f"stage-{index}", agent_id, agent_version, brief)
            for index, (agent_id, agent_version) in enumerate(pins)
        ],
    }


def agent_markdown(agent_id: str, version: int, body: str = "Do the work.\n") -> bytes:
    text = f"---\nname: {agent_id}\nid: {agent_id}\nversion: {version}\n---\n\n{body}"
    if not text.endswith("\n"):
        text += "\n"
    return text.encode("utf-8")


def belt_package(package_id: str = "issue-flow", version: int = 1, **belt_kwargs: object) -> dict[str, bytes]:
    root = f"packages/{package_id}/v{version}"
    return {
        f"{root}/package.json": dumps(manifest(package_id, "belt", "Issue flow", "Triage an issue and build it.", ["issues"])),
        f"{root}/belts/issues/v1.json": dumps(belt(**belt_kwargs)),
        f"{root}/agents/triage/v1.md": agent_markdown("triage", 1),
    }


def agent_package(
    package_id: str = "review", version: int = 1, agent_version: int = 1, body: str = "Review the change.\n"
) -> dict[str, bytes]:
    root = f"packages/{package_id}/v{version}"
    return {
        f"{root}/package.json": dumps(manifest(package_id, "agent", "Review", "Review a pull request.", [])),
        f"{root}/agents/review/v{agent_version}.md": agent_markdown("review", agent_version, body),
    }


def factory_package(package_id: str = "team-setup", version: int = 1) -> dict[str, bytes]:
    """Factory with historical pins, a belt-version gap, an unpinned agent and no agent flag."""
    root = f"packages/{package_id}/v{version}"
    name = "Team setup"
    files = {
        f"{root}/package.json": dumps(manifest(package_id, "factory", name, "The belts and agents used for issue work.", ["team"])),
        f"{root}/factory.json": dumps({"schemaVersion": 1, "id": package_id, "name": name}),
        f"{root}/README.md": b"Shared factory for issue work.\n",
        f"{root}/belts/issues/v1.json": dumps(belt(version=1, pins=[("triage", 1)])),
        f"{root}/belts/issues/v3.json": dumps(belt(version=3, pins=[("triage", 2)])),
        f"{root}/belts/issues/state.json": dumps({"archived": False, "paused": True}),
        f"{root}/agents/triage/v1.md": agent_markdown("triage", 1, "Triage the issue.\n"),
        f"{root}/agents/triage/v2.md": agent_markdown("triage", 2, "Triage the issue again.\n"),
        f"{root}/agents/scribe/v1.md": agent_markdown("scribe", 1, "Write the note.\n"),
    }
    return files


def factory_without_belts(package_id: str = "agents-only") -> dict[str, bytes]:
    root = f"packages/{package_id}/v1"
    name = "Agents only"
    return {
        f"{root}/package.json": dumps(manifest(package_id, "factory", name, "Agents with no belts.")),
        f"{root}/factory.json": dumps({"schemaVersion": 1, "id": package_id, "name": name}),
        f"{root}/agents/review/v1.md": agent_markdown("review", 1),
    }
