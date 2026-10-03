# Contributing

Packages in this repository follow the format in [README.md](README.md): the [manifest](README.md#manifest), the [layouts](README.md#layouts) for a factory, a belt and an agent, and the [stripping rules](README.md#what-a-shared-package-keeps).

A package is published only when a pull request has been reviewed and merged. Do not push commits directly to the default branch. The default branch is currently `main`. Existing versions stay as they were merged; a change is a new `packages/<id>/v<n>/` directory.

Share… in the app is planned. It is not part of this repository, and these documents do not add it. Until it is available, prepare the package by hand.

## Share from the app

The planned Share… action is on Belts (one belt), on Agents (one agent) and on Settings → Factories (the whole library as a factory package).

1. Choose Share… on that page.
2. Enter the package name, a one-line summary, tags and an optional README.
3. Read the preview. It shows the stripped package: every belt has `repos` set to `[]`, `base` set to `""` and `afkEnabled` set to `false`, and a factory's belt flag files are paused.
4. The app opens a pull request for review. The branch is `beltline/<id>-v<n>` in your fork of this repository, or in the marketplace repository itself when you are its owner. `<id>` is the package id and `<n>` is one past the highest version that package already has. The pull request targets the marketplace's default branch, currently `main`. Versions already on that branch are left intact.

The pull request is the proposal. It is public only after it is reviewed and merged.

## Share by hand

1. Fork this repository. An owner of the marketplace can branch the marketplace itself instead of a fork.
2. Create a branch. Do the work on that branch. Do not commit on the default branch, and do not push the default branch.
3. Add a new version folder, `packages/<id>/v<n>/`, with the files in the [README layouts](README.md#layouts). `<n>` is one past the highest existing version of that package. Keep the same package id and kind. Leave every existing version folder untouched.
4. Strip the belt settings the same way the app would. In every belt version, including every version inside a factory, set `repos` to `[]`, `base` to `""` and `afkEnabled` to `false`. In a factory package, set each belt's `state.json` `paused` flag to `true` and keep its `archived` flag.
5. Open a pull request against the marketplace's default branch, currently `main`.

Opening that pull request is how a hand-written package is proposed. Do not push those commits straight to `main`.

## Reviewer checks

Review the pull request, then merge it. Merging is what publishes the version. Closing it leaves the marketplace unchanged.

- Manifest and layout. `package.json` is schemaVersion 1, its `id` matches the package folder, and its `kind` matches the tree in the [README](README.md#layouts). A belt package has exactly one belt and the agent versions that belt pins, and no unpinned agent. An agent package has exactly one agent and no belts. A factory package has `factory.json`, every saved belt and agent version, at least one agent, and an agent file for every historical pin.
- Dependency pins. Every agent a belt stage pins is present at that id and version. A factory still contains the older agent versions its older belt versions pin.
- Immutable versions. The pull request adds a new version and does not change a version that has already merged. The package id and kind stay the same.
- Description. The summary is useful in one line. The optional README, when present, helps someone decide whether to import the package.
- Sensitive information. Read every definition, brief, filter and piece of documentation in the pull request, including the optional README. Refuse secrets, tokens, private repository names and personal paths. Empty `repos` and `base` fields do not make that text safe.
