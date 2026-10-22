# Contributing

Every belt and agent arrives as a pull request and is published when it is merged. Don't push to `main`.

## What a good contribution has

- **A clear name and a brief that stands on its own.** Someone who has never seen your setup should understand what the agent does and when each outcome applies.
- **No private details.** No internal hostnames, ticket keys, customer names, tokens or paths on your machine in briefs, triggers or policies. Beltline strips a belt's repositories and base branch, but not what you wrote in a brief or a JQL query.
- **Every agent version a belt uses.** Sharing from Beltline adds them for you.
- **A note in the pull request** saying what the item is for and what you ran it on.

## Rules

- A merged version never changes. To change an item, add `v<n+1>` beside the versions already here.
- A new version keeps its id. A different item gets a different id.
- Belts carry no repositories (`triggers[].repos` empty), no `base`, no `repositoryBases` and no `origin`.
- Files go under `belts/<id>/v<n>.json` or `agents/<id>/v<n>.md`; nothing else under `belts/` or `agents/`.

The `check` workflow runs `scripts/check.py` on every pull request and enforces these rules. Run it yourself with:

```sh
python3 scripts/check.py --base origin/main
```

Beltline itself checks that a belt's stages and the agents they pin fit together. `beltlined --check-library <clone>` prints what it finds wrong in a clone of this repository.

## Share by hand

1. Fork this repository and create a branch.
2. Copy the item from your Beltline data folder: `belts/<id>/v<n>.json` or `agents/<id>/v<n>.md`, and for a belt, every `agents/<id>/v<n>.md` its stages pin that isn't here yet.
3. In the belt, empty each trigger's `repos`, set `base` to `""`, and remove `repositoryBases` and `origin`. In an agent, remove `origin` and `originPath` from the frontmatter.
4. Run the check, then open a pull request.

By opening a pull request you agree to share your contribution under the [Apache License 2.0](LICENSE).
