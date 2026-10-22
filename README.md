# Beltline marketplace

Belts and agents for [Beltline](https://github.com/robbertmanders/beltline), shared in the open. Add this repository to Beltline, install what you need, and share your own back as a pull request.

## Use it

1. In Beltline, open **Settings → Library repositories** and add `robbertmanders/beltline-marketplace` as a **Shared** repository, published by **Pull request**. Leave the path empty.
2. Open **Library**. It lists every belt and agent here, with what you have installed and what has an update.
3. **Install** a belt. Beltline also installs the agent versions it uses, so it is ready to run.
4. Fill in what a shared belt leaves out: the repositories its trigger watches and its base branch. Then allow the models its agents use under **Settings → Allowed models**, or pick ones you allow.

An installed item remembers this repository as its origin. When a newer version is merged here, Library offers **Update**; the versions you had stay, and runs keep the versions they started with.

Read Beltline's [security model](https://github.com/robbertmanders/beltline/blob/main/docs/security.md) before you run a belt from someone else. Agents run with their approval prompts turned off, as you, so read an agent's brief and a belt's stages before you install them.

## Share yours

On **Belts** or **Agents** in Beltline, choose **Share** on a saved version and pick this repository. Beltline opens a pull request with the item, plus the agent versions a belt uses. It leaves out what belongs to your setup: a belt's repositories, base branch, AFK mode and origin.

Once the pull request is reviewed and merged, everyone who has this repository added sees it in Library. See [CONTRIBUTING.md](CONTRIBUTING.md) for the rules and for sharing by hand.

## Layout

This repository is laid out like a Beltline library:

```text
belts/<id>/v<n>.json   one version of a belt
agents/<id>/v<n>.md    one version of an agent: settings and outcomes in the frontmatter, the brief as the body
```

`<id>` is letters, digits, dashes and underscores, and `<n>` counts up from 1. Other files, such as this README, are ignored by Beltline.

A version never changes once it is merged: a change is the next version. The `check` workflow enforces this and checks that shared belts carry no repositories, base branch or origin.

## License

Everything here is shared under the [Apache License 2.0](LICENSE), the same license as Beltline.
