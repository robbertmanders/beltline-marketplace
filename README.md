# Beltline marketplace

This repository is the public marketplace for sharing Beltline factories, belts and agents. The planned Market page is where people browse those packages, preview one, and import it. Publication is moderated through pull requests: a package is proposed in a pull request, and it is shared when that pull request is reviewed and merged.

The Market page and Share… are planned. This documentation describes that workflow and the package format. It does not add either feature to the app.

Importing a factory package replaces the belts and agents in your library. Importing a belt or agent package adds it to the library beside what you already have.

Your own factory repository, and Settings → Factories, keep the archive format they already use. A personal factory backup lives under `factories/<id>/v<n>/` and still contains that setup's repositories and base branches. Marketplace packages live under `packages/<package>/v<n>/` and are prepared for someone else, as described below.

## Manifest

Every package version has a manifest at `packages/<package>/v<n>/package.json`. The same file is used for a factory, a belt and an agent.

An optional `packages/<package>/v<n>/README.md` may sit beside it. The file is UTF-8 Markdown and is shown in the preview.

`package.json` has exactly these keys:

- `schemaVersion`: the integer `1`
- `id`: a string, the same as the `<package>` folder name
- `name`: a non-empty display-name string
- `kind`: a string, one of `factory`, `belt` or `agent`
- `summary`: a one-line string
- `author`: the publisher's GitHub login, as a string
- `tags`: an array of free-word strings, which may be empty

Unknown keys are refused. A `schemaVersion` other than `1` is refused. A `kind` other than `factory`, `belt` or `agent` is refused.

A belt package:

```json
{
  "schemaVersion": 1,
  "id": "issue-flow",
  "name": "Issue flow",
  "kind": "belt",
  "summary": "Triage an issue, build it and open a pull request.",
  "author": "octocat",
  "tags": ["issues", "build"]
}
```

An agent package, with no tags:

```json
{
  "schemaVersion": 1,
  "id": "review",
  "name": "Review",
  "kind": "agent",
  "summary": "Review a pull request and post the result.",
  "author": "octocat",
  "tags": []
}
```

A factory package:

```json
{
  "schemaVersion": 1,
  "id": "team-setup",
  "name": "Team setup",
  "kind": "factory",
  "summary": "The belts and agents used for issue work.",
  "author": "octocat",
  "tags": ["team"]
}
```

## Layouts

`n` is the package version. `k` is the publisher's version of one belt or agent definition. The two numbers are independent. The optional README may be omitted from any of the trees below.

A belt file, `belts/<id>/v<k>.json`, is a Beltline belt definition in JSON. An agent file, `agents/<id>/v<k>.md`, is Markdown: settings and outcomes in the frontmatter, and the brief as the body. When that frontmatter sets `id` or `version`, the value has to agree with the file's path.

### Belt

A belt package contains exactly one belt definition, `belts/<id>/v<k>.json`, and one `agents/<id>/v<k>.md` for every agent version that belt pins. Every agent file is pinned by that belt. It has no second belt, no `state.json`, no `factory.json`, and no other payload path.

```text
packages/issue-flow/v1/package.json
packages/issue-flow/v1/README.md            optional
packages/issue-flow/v1/belts/issues/v3.json
packages/issue-flow/v1/agents/triage/v2.md
packages/issue-flow/v1/agents/build/v1.md
```

### Agent

An agent package contains exactly one agent file, `agents/<id>/v<k>.md`. It contains no belts, no `state.json`, no `factory.json`, and no other payload path.

```text
packages/review/v1/package.json
packages/review/v1/README.md                 optional
packages/review/v1/agents/review/v4.md
```

### Factory

A factory package contains `factory.json`, every saved belt version, and every saved agent version. `belts/<id>/state.json` and `agents/<id>/state.json` are optional flag files. The archive contains at least one agent. Every pin in every belt version, including older versions, resolves to an agent file in the package: a belt that once pinned `agents/triage/v1.md` still needs that file when a later belt version pins `agents/triage/v2.md`.

`state.json` and `factory.json` belong only in a factory package. Any other payload path is unsupported.

```text
packages/team-setup/v2/package.json
packages/team-setup/v2/README.md             optional
packages/team-setup/v2/factory.json
packages/team-setup/v2/belts/issues/v1.json
packages/team-setup/v2/belts/issues/v3.json
packages/team-setup/v2/belts/issues/state.json
packages/team-setup/v2/agents/triage/v1.md
packages/team-setup/v2/agents/triage/v2.md
packages/team-setup/v2/agents/build/v1.md
packages/team-setup/v2/agents/triage/state.json
packages/team-setup/v2/agents/build/state.json
```

`factory.json` has exactly `schemaVersion`, `id` and `name`. Its `schemaVersion` is the integer `1`. Its `id` is the factory archive's id, and its `name` is that factory's display name.

```json
{
  "schemaVersion": 1,
  "id": "team-setup",
  "name": "Team setup"
}
```

A belt flag file carries `paused` and `archived`. An agent flag file carries `archived`.

## Identities and versions

A package has four separate identities:

- The package id is the `<package>` folder. Package ids share one namespace across factories, belts and agents, so the same id cannot be used for two kinds.
- A belt id or an agent id is the `<id>` folder under `belts/` or `agents/`. Those ids are not package ids.
- The package version is `n` in `packages/<package>/v<n>/`.
- The definition version is `k` in `belts/<id>/v<k>.json` or `agents/<id>/v<k>.md`.

In `packages/example/v2/agents/review/v7.md` the package id is `example`, the package version is 2, the agent id is `review` and the agent version is 7. Changing the agent from version 7 to version 8 does not by itself publish a new package version.

The app makes a package id from the package name: lowercase ASCII letters, digits and dashes (`-`). Characters other than ASCII letters and digits collapse to a single dash between the remaining parts, dashes at either end are dropped, and a name with no ASCII letter or digit produces no id. `Issue flow` becomes `issue-flow`.

A hand-written id may use ASCII letters of either case, digits, hyphens and underscores. An id cannot be empty, `.` or `..`. Every payload path is a safe regular file: no symlink, and no path that traverses with `.` or `..`.

Version numbers are positive integers (`v1`, `v2`, and so on). A belt definition's id and version agree with its path. An agent file's identity frontmatter cannot contradict its path. Package versions do not have to match definition versions.

A merged package version is immutable. Its files stay as they were merged, so a merged `v2` is never edited. Publish a change as a new directory numbered one past the highest version that package already has, keeping the same package id and kind. When `v2` is the highest, the change is `v3`. When the published versions are `v1` and `v4`, the change is `v5`.

## What a shared package keeps

Every shared belt version, including every belt version inside a factory, is stored with:

- `repos` = `[]`
- `base` = `""`
- `afkEnabled` = `false`

Imported belts arrive paused, so the recipient can set repositories before enabling the belt. In a factory package each belt's `state.json` sets `paused` to `true` and keeps that belt's `archived` flag.

The package keeps triggers and their filters, policies, stages, forks, briefs and model choices.

The package never includes runs, sessions, checkouts, settings, credentials, local model allowances, schedule firing history or the factory origin.

Clearing `repos`, `base` and `afkEnabled` does not sanitize free text. Briefs and filters can still contain a secret, a token, a private repository name or a personal path. A person has to read that text before the package is published. [CONTRIBUTING.md](CONTRIBUTING.md) is the checklist for that review.
