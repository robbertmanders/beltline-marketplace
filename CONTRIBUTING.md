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
4. Strip the belt settings the same way the app would. In every belt version, including every version inside a factory, set `repos` to `[]`, `base` to `""` and `afkEnabled` to `false`. In a factory package, every belt requires `state.json` with `paused` set to `true` and a boolean `archived`. Agent `state.json` remains optional and may contain only a boolean `archived`.
5. Run the package check and its tests. Fix every blocking failure before opening the pull request.

   ```bash
   python3 scripts/check_packages.py --base origin/main
   python3 -m unittest discover -s tests -v
   ```

6. Open a pull request against the marketplace's default branch, currently `main`.

Opening that pull request is how a hand-written package is proposed. Do not push those commits straight to `main`.

## Reviewer checks

Contributors run the check locally with Python 3 and the standard library. No extra Python packages are installed, and Beltline itself is not built:

```bash
python3 scripts/check_packages.py --base origin/main
```

The checker compares the committed `HEAD` with the base commit. It reads Git trees and blobs, so it does not follow symlinks or run anything in the package. The unit tests are:

```bash
python3 -m unittest discover -s tests -v
```

GitHub Actions runs those tests and the checker as `check-packages` on every pull request to `main`, including forks and documentation-only or placeholder-only proposals, and on every push to `main`. A blocking failure is a GitHub error annotation and a nonzero exit status. A warning is a GitHub warning annotation for secret-like text or a personal path. Warnings alone do not fail the check. They still need a person to review them.

Published versions are immutable. The check fails if a version already on the base branch is edited, deleted, renamed or has a file mode change, even when the proposal also adds a newer version. A change is a new version directory: `v1` for a new package, or one past the highest published version.

Review the pull request, then merge it. Merging is what publishes the version. Closing it leaves the marketplace unchanged. Automated failures and warnings are not a substitute for that review.

- Manifest and layout. `package.json` is schemaVersion 1, its `id` matches the package folder, and its `kind` matches the tree in the [README](README.md#layouts). A belt package has exactly one belt and the agent versions that belt pins, and no unpinned agent. An agent package has exactly one agent and no belts. A factory package has `factory.json`, every saved belt and agent version, at least one agent, and an agent file for every historical pin.
- Dependency pins. Every agent a belt stage pins is present at that id and version. A factory still contains the older agent versions its older belt versions pin.
- Immutable versions. The pull request adds at most one new version and does not change a version that has already merged. The package id and kind stay the same. When the published versions are `v1` and `v4`, the next version is `v5`.
- Description. The summary is useful in one line. The optional README, when present, is UTF-8 and at most 64 KB, and helps someone decide whether to import the package.
- Sensitive information. Read every definition, brief, filter and piece of documentation in the pull request, including the optional README. The checker rejects a private repository listed in `repos`, including a legacy trigger-level `repos` or `base`, and it warns on secret-like text and personal paths. It does not look up whether a repository is public. It does not reject a private repository name written only in free text. Reviewers must check free text for private repository references. Refuse secrets, tokens, private repository names and personal paths. Empty `repos` and `base` fields do not make that text safe.
