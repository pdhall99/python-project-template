# Contributing

This is a personal template, so this guide is for maintaining it rather than for outside contributions: pull requests from others aren't accepted.

## Contents

- [Repository layout](#repository-layout)
- [Changing the template](#changing-the-template)
- [Testing changes](#testing-changes)
- [Releasing a version](#releasing-a-version)
- [Making the yearly updates](#making-the-yearly-updates)

## Repository layout

- `copier.yml`: the questions, their validators and the Copier settings
- `new-project.py`: creates a project, pushes it to a new GitHub repository and configures the repository (`hatch run new-project`)
- `template/`: the files Copier renders into a project; files ending in `.jinja` are rendered, and the rest are copied as they are
- `github-settings/`: the GitHub settings for generated projects:
  - `configure.py` applies them to a repository (`hatch run configure`)
  - `compare.py` compares the settings of repositories (`hatch run compare`)
  - `_github.py` makes GitHub API requests through the GitHub CLI for both
  - `rulesets/` holds the rulesets `configure.py` applies
- `tests/`: tests for the scripts and the template
- `pyproject.toml`: the Hatch environments, scripts and tool versions, Copier's included; the repository isn't a Python package
- `.pre-commit-config.yaml`: the repository's own pre-commit hooks
- `.github/workflows/ci.yml`: the `CI` workflow, which runs the tests and checks projects rendered from the template
- `CHANGELOG.md`: the template's own changes, including any manual steps projects need after updating

## Changing the template

### Writing Jinja

The template uses its own Jinja delimiters, so that GitHub Actions expressions and other `{{ }}` and `{% %}` text need no escaping:

- `[[[ ]]]` for variables
- `[% %]` for blocks
- `[# #]` for comments

A `-` inside a block tag removes all whitespace on that side, including blank lines.
Use `-%]` only where the newline after the tag should go.
Put tags that include or leave out whole YAML blocks on the blank lines between them, without `-`, so the indentation survives.
For a value that depends on an answer, keep the condition inside the line, as the `Changelog` URL in `pyproject.toml.jinja` does.

Rendered files must need no changes from the generated project's pre-commit hooks, in particular pyproject-fmt.

Answers that go into TOML strings pass through the `toml_escape` macro in `pyproject.toml.jinja`.
When adding a free-text question, add it to `test_answers_are_escaped` in `tests/test_template.py`, and add answers its validator should reject to `test_rejects_invalid_answers`.

### Adding files

Files listed in `_skip_if_exists` in `copier.yml` are created once and never updated, because each project rewrites them.
Add a file there only if projects are expected to replace its contents; Copier recreates it if a project deletes it.

### Bumping pinned versions

Dependabot can't update the pinned versions inside `template/`, because the files there are Jinja templates.
Bump them from a generated project, where Dependabot opens the pull requests, then copy the new pins into the template.

Copy each pin exactly as Dependabot wrote it, commit SHA and version comment included.
`copier update` then sees the same change on both sides and applies it cleanly to projects that already have it; any other version conflicts on every line it appears.

Keep each action's version comment as the full version, such as `# v7.0.1`, because zizmor checks it against the pinned commit.
Pre-commit hooks are pinned the same way, with the version in a `# frozen: v6.0.0` comment, as `pre-commit autoupdate --freeze` writes them.
In projects, the `ruff-version` hook checks that `ruff` in `pyproject.toml` matches the `ruff-pre-commit` hook, so bump both together.

Dependabot does update the actions in the `CI` workflow and the hooks in this repository's `.pre-commit-config.yaml`.
The tool versions in the workflow's `env` block and in `pyproject.toml` need bumping by hand, in line with the template's.
Copier's version in `pyproject.toml` is the one CI tests and the scripts use; raise `_min_copier_version` in `copier.yml` to match when the template starts relying on a newer Copier.

## Testing changes

Run the tests with Hatch, from anywhere in the clone:

```shell
hatch test  # Run the tests
hatch test --all  # Run them on every supported Python, as CI does
```

The tests in `tests/test_template.py` render the template as it is in your working tree, uncommitted changes included.
They check the rendered configuration for every combination of the policy and documentation options, the escaping and validation of answers, and that turning the docs off with an update leaves the same files as a fresh render without docs.
The other tests check the scripts and the rulesets.

The `CI` workflow runs the tests, then renders every combination of the options and runs each project's own checks, tests on every supported Python, pre-commit hooks, build and docs build.
Its `update` job renders the version being updated from (a pull request's base, otherwise the latest earlier tag), changes the project as a real one would, then runs `copier update` to the new version.
It fails if the update conflicts, loses the project's changes, or leaves the project failing its checks.
It also runs this repository's pre-commit hooks, which check the scripts and the workflow itself.

To run a rendered project's own checks locally, render one from your working tree, starting from the clone's root:

```shell
hatch run copier copy --vcs-ref HEAD --defaults \
  -d project_name=demo-pkg -d project_description="A demo" \
  -d github_owner=pdhall99 -d author_name="PD Hall" -d author_email=demo@example.com \
  -d python_support=eol -d docs_enabled=true \
  . /tmp/demo-pkg
cd /tmp/demo-pkg
git init && git add -A && git commit -m "Initial commit"
hatch run pre-commit:ci
git status --short  # Prints nothing if the hooks changed nothing
hatch run docs:build
```

Without `--vcs-ref HEAD`, Copier renders the newest tag rather than your changes.
If the change touches a conditional part of the template, also try `python_support=spec0` and `docs_enabled=false`.

### Checking the scripts

The scripts are plain Python, run by Hatch scripts in the default environment, whose dependencies are the `scripts` group in `pyproject.toml`: Copier and PyYAML.
Keep them to the standard library and that group.

The repository is developed with Hatch, like generated projects.
It isn't a Python package, so its Hatch environments are standalone: they install the tools pinned in `pyproject.toml`, not the repository.

The scripts' tests replace GitHub, Hatch and `configure.py` with fakes, and send pushes to a local repository, so they never touch GitHub.
The pre-commit hooks lint, format and type-check the scripts and tests, check the workflow with actionlint and zizmor, and check every file's whitespace and syntax:

```shell
hatch test --all  # Run the tests on every supported Python
hatch check types  # Type-check the scripts with Pyrefly
hatch run pre-commit:install  # Run the hooks on each commit
hatch run pre-commit:ci  # Run all the hooks on every file
```

## Releasing a version

Projects update to the newest tag, so changes on `main` reach them only once they're tagged.

1. Record each change under `[Unreleased]` in `CHANGELOG.md` as you make it, with any manual steps projects need after `copier update`.
2. Rename `[Unreleased]` to the new version and date, add a new empty `[Unreleased]` above it, and update the links at the bottom.
   The template has tags but no GitHub releases, so the first version links to its tag and later ones compare with the previous version:

   ```markdown
   [Unreleased]: https://github.com/pdhall99/python-project-template/compare/1.1.0...HEAD
   [1.1.0]: https://github.com/pdhall99/python-project-template/compare/1.0.0...1.1.0
   [1.0.0]: https://github.com/pdhall99/python-project-template/tree/1.0.0
   ```
3. Merge, then tag `main` and push the tag:

   ```shell
   git switch main && git pull
   git tag X.Y.Z
   git push origin X.Y.Z
   ```

Use Semantic Versioning, from the point of view of a project being updated:

- **MAJOR** for changes that need manual steps in projects
- **MINOR** for new questions, options or files
- **PATCH** for fixes

Copier orders tags as PEP 440 versions, so use plain `X.Y.Z` tags.

## Making the yearly updates

Two defaults in `copier.yml` need updating once a year:

- each October, update the supported Python versions for both policies: a new Python release comes out, and older ones reach their SPEC 0 drop date or end of life; update the scripts' test matrix in this repository's `pyproject.toml` to match the end-of-life list;
- each January, update the `copyright_year` default.

Release a new version after each update, so projects pick the change up with `copier update`.
