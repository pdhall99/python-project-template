# python-project-template

[![CI](https://img.shields.io/github/actions/workflow/status/pdhall99/python-project-template/ci.yml?branch=main)](https://github.com/pdhall99/python-project-template/actions/workflows/ci.yml)

Create and update typed Python libraries with Hatch, uv, Ruff, Pyrefly and GitHub Actions, using Copier.

This repository holds the Copier template and the scripts used to create and update Python libraries owned by [@pdhall99](https://github.com/pdhall99).
The template records the conventions the libraries share.
The scripts create each library's GitHub repository, configure its settings and check that they stay in line.

Each generated library has

- a `src/` layout
- Versioning from Git tags with Hatch-VCS
- Hatch environments, installed with uv
- Ruff for linting and formatting, and Pyrefly in strict mode for type checking
- pytest and coverage, with doctests in the package and the README
- pre-commit hooks, including pyproject-fmt, actionlint and zizmor
- a GitHub Actions workflow that runs the hooks, the tests on every supported Python, and the package and docs builds
- releases from `X.Y.Z` tags, published to PyPI by trusted publishing, with GitHub release notes from `docs/CHANGELOG.md`
- optionally, a Zensical documentation site on GitHub Pages
- Dependabot updates for the pinned actions and pre-commit hooks
- supported Python versions that follow SPEC 0 or upstream end of life, and move forward with each template release

## Table of contents

- [Installation](#installation)
- [Usage](#usage)
- [Acknowledgements](#acknowledgements)
- [Contributing](#contributing)
- [License](#license)

## Installation

You will need:

- a GitHub account, with the [GitHub CLI](https://cli.github.com/) signed in to it (`gh auth login`), to create, configure and compare repositories
- [Git](https://git-scm.com/)
- [Hatch](https://hatch.pypa.io/) 1.18 or later
- internet access, for GitHub and for installing packages from PyPI

If Hatch isn't installed, see the [Hatch installation instructions](https://hatch.pypa.io/latest/install/).

To set up the tools, clone this repository:

```shell
git clone https://github.com/pdhall99/python-project-template.git
cd python-project-template
```

Run the commands in the [Usage](#usage) section from inside the clone.

To get the latest versions of the scripts, run `git pull` in the clone.

## Usage

### Creating a project

```shell
hatch run new-project ~/projects/my-project  # add --private for a private repository
```

The command:

1. copies the template from GitHub with Copier, which asks for the project's name, description and other details;
2. commits the project and installs its pre-commit hooks;
3. creates the GitHub repository, pushes to it and sets its description to the project's;
4. configures the repository, as described below.

If a step fails, fix the cause and run the command again: it skips the steps already done.
If the folder is inside another Git repository, it gets a repository of its own, so the outer one is never committed to or pushed.
The command refuses to continue if `origin` points to a different repository, or if the GitHub repository already exists with the other visibility.
Add `--vcs-ref BRANCH` to try an unreleased change.

Paths are relative to where you run the command, so give the project's full path.

To create only the files, run Copier on its own:

```shell
hatch run copier copy gh:pdhall99/python-project-template ~/projects/my-project
```

Copier then prints the command for the remaining steps.
Without a clone, `uvx copier copy gh:pdhall99/python-project-template my-project` does the same, with the latest Copier.

### Configuring the GitHub repository

`new-project` configures the new repository.
To configure an existing repository, or apply changed settings again, run the configuration on its own:

```shell
hatch run configure OWNER/REPO  # add --dry-run to see the changes first
```

The script uses the GitHub CLI, and can be run again safely.
If GitHub refuses a setting, the script applies the rest, then lists the ones not applied and exits with status 1.
It sets up:

- repository settings: no wiki, discussions or projects; squash merging only, with the pull request title as the commit message; always suggest updating pull request branches; delete head branches after merging;
- Dependabot alerts and security updates, alongside the version updates in the project's `.github/dependabot.yml`;
- secret scanning, with push protection blocking pushes that contain secrets;
- GitHub Actions settings: every action must be pinned to a full-length commit SHA, and workflow runs from all outside contributors' pull requests wait for your approval;
- GitHub Pages deployed from GitHub Actions, if the project has a docs site;
- a `pypi` environment that only release tags can deploy to, removing any other deployment policies, with your approval before each upload (`--no-reviewer` to skip it);
- the rulesets in [`github-settings/rulesets/`](github-settings/rulesets/):
  - `main`: changes arrive through squash-merged pull requests that are up to date with `main`, pass the `CI gate` check and have every conversation resolved, with no bypass;
  - `release tags`: only admins can create, move or delete `X.Y.Z` tags; admins can move a tag whose release failed before publishing, as the generated contributor guide describes, but must never move a published one.

To change a ruleset, edit its file, or export one from a repository's settings (**Rules** → **Rulesets** → **Export ruleset**) and remove its `id`, `source` and `source_type` fields.
To check that repositories have the same settings, compare them with a reference repository:

```shell
hatch run compare OWNER/REFERENCE OWNER/REPO [OWNER/REPO ...]
```

The script shows the differences from the reference for each repository, and saves every repository's settings as JSON files.
It covers the settings above, and a few others, such as whether issues are enabled.
A setting it can't read is shown as unknown rather than off, and any difference or unknown setting makes it exit with status 1.

On GitHub Free, rulesets and environment reviewers only work in public repositories, so on a private repository `configure` lists them as not applied.
It never removes a reviewer because GitHub refused one: run it with `--no-reviewer` to set up the `pypi` environment without your approval.

One setting is on PyPI rather than GitHub: add a [trusted publisher](https://docs.pypi.org/trusted-publishers/) (a pending publisher, before the first release) with workflow `ci.yml` and environment `pypi`.

### Updating a project

Projects include `.copier-answers.yml`, so later template releases can be applied, giving the project's path:

```shell
hatch run update ~/projects/my-project
```

Copier updates to the newest tagged release.
Options pass through to `copier update`, such as `--vcs-ref BRANCH`, or `-d docs_enabled=true` to change an answer.
Check the [changelog](CHANGELOG.md) for any manual steps.

Each template release can change the supported Python versions, so record any change in the project's changelog.

## Acknowledgements

This repository is developed with assistance from AI coding tools.
All code included in the repository is reviewed and tested by [@pdhall99](https://github.com/pdhall99), who takes responsibility for its quality and maintenance.

## Contributing

This repository is a personal tool, so pull requests and feature requests aren't accepted.
Bug reports are welcome as [issues](https://github.com/pdhall99/python-project-template/issues).
You're welcome to fork it and adapt it to your own conventions.

See [CONTRIBUTING.md](CONTRIBUTING.md) for notes on maintaining this repository.

## License

[MIT © PD Hall](LICENSE)
