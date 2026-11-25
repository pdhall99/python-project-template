"""Tests that render the template with Copier and check the files it writes.

They render the template as it is in the working tree, uncommitted changes
included, so they check work in progress. Answers are strings, as from
`copier copy -d`, so Copier's parsing of them is tested too. Running a rendered
project's own checks, tests, build and docs build is left to the CI workflow.
"""

import ast
import os
import re
import shutil
import subprocess
import tomllib
from pathlib import Path
from typing import Any

import copier
import pytest
import yaml

from conftest import ROOT

ANSWERS = {"project_name": "example-project", "project_description": "Example project"}


@pytest.fixture(scope="session")
def template(tmp_path_factory: pytest.TempPathFactory) -> Path:
    """Return a one-commit repository holding the template from the working tree.

    Copier renders commits. Rendering this one, rather than the clone, includes
    uncommitted changes, works in a shallow clone, and gives an update a commit
    to find. Files Git ignores are left out.
    """
    snapshot = tmp_path_factory.mktemp("template")
    listed = subprocess.run(
        ["git", "ls-files", "-z", "--cached", "--others", "--exclude-standard"]
        + ["--", "copier.yml", "template"],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=True,
    ).stdout
    for name in filter(None, listed.split("\0")):
        source = ROOT / name
        if source.is_file():  # Not deleted since it was staged
            (snapshot / name).parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source, snapshot / name)
    # Without the user's Git configuration, which may sign commits, for example.
    env = {**os.environ, "GIT_CONFIG_GLOBAL": os.devnull, "GIT_CONFIG_NOSYSTEM": "1"}
    identity = ["-c", "user.name=Test", "-c", "user.email=test@example.com"]
    for args in (
        ["init", "--quiet"],
        ["add", "--all"],
        [*identity, "commit", "--quiet", "--message", "Snapshot"],
    ):
        subprocess.run(["git", *args], cwd=snapshot, env=env, check=True)
    return snapshot


def render(template: Path, destination: Path, **answers: str) -> Path:
    """Render the template into destination, with ANSWERS and any others."""
    copier.run_copy(
        str(template),
        destination,
        data={**ANSWERS, **answers},
        defaults=True,
        vcs_ref="HEAD",
        quiet=True,
    )
    return destination


def version_key(version: str) -> tuple[int, ...]:
    return tuple(map(int, version.split(".")))


def test_answers_are_escaped(template: Path, tmp_path: Path) -> None:
    """Quotes and backslashes in free-text answers survive into every file."""
    root = render(
        template,
        tmp_path / "awkward",
        project_name="awkward-project",
        project_description='A "quoted" project with a back\\slash',
        runtime_dependencies='["numpy>=2; python_version >= \\"3.12\\""]',
        keywords='["say \\"hi\\""]',
        author_name='Pat "PD" Hall',
    )

    project = tomllib.loads((root / "pyproject.toml").read_text())["project"]
    assert project["description"] == 'A "quoted" project with a back\\slash'
    assert project["dependencies"] == ['numpy>=2; python_version >= "3.12"']
    assert project["keywords"] == ['say "hi"']
    assert project["authors"][0]["name"] == 'Pat "PD" Hall'
    site = tomllib.loads((root / "zensical.toml").read_text())["project"]
    assert site["site_description"] == project["description"]
    assert site["site_author"] == 'Pat "PD" Hall'
    module = ast.parse((root / "src/awkward_project/__init__.py").read_text())
    assert ast.get_docstring(module) == project["description"] + "."


@pytest.mark.parametrize(
    ("question", "answer"),
    [
        ("project_name", "-bad-name"),
        ("package_name", "class"),
        ("package_name", "1example"),
        ("project_description", "Ends with a full stop."),
        ("project_description", "Ends with a question?"),
        ("project_description", "Ends with an exclamation!"),
        ("project_description", "Two\nlines"),
        ("keywords", "not-a-list"),
        ("keywords", '["two\\nlines"]'),
        ("runtime_dependencies", "{a: 1}"),
        ("runtime_dependencies", '["numpy\\t>=2"]'),
        ("github_owner", "not_an_owner"),
        ("author_name", "PD\nHall"),
        ("author_name", "PD\tHall"),
        ("author_name", " "),
        ("author_email", "not-an-email"),
    ],
)
def test_rejects_invalid_answers(
    template: Path, tmp_path: Path, question: str, answer: str
) -> None:
    """Each invalid answer fails its own question's validator, not something else."""
    expected = f"Validation error for question '{question}'"
    with pytest.raises(ValueError, match=re.escape(expected)):
        render(template, tmp_path / "rejected", **{question: answer})


@pytest.mark.parametrize("docs", ["true", "false"])
@pytest.mark.parametrize("python_support", ["spec0", "eol"])
def test_rendered_configuration(
    template: Path, tmp_path: Path, python_support: str, docs: str
) -> None:
    root = render(
        template,
        tmp_path / "project",
        python_support=python_support,
        docs_enabled=docs,
    )
    pyproject = tomllib.loads((root / "pyproject.toml").read_text())
    project = pyproject["project"]
    tool = pyproject["tool"]
    hatch = tool["hatch"]["envs"]

    # Every Python version setting agrees with the test matrix.
    expected: list[str] = hatch["hatch-test"]["matrix"][0]["python"]
    assert expected == sorted(expected, key=version_key)
    minimum, newest = expected[0], expected[-1]
    assert project["requires-python"] == f">={minimum}"
    assert project["import-names"] == ["example_project"]
    classifiers = [
        c.rsplit(" :: ", 1)[1]
        for c in project["classifiers"]
        if c.startswith("Programming Language :: Python :: 3.")
    ]
    assert classifiers == expected
    assert hatch["default"]["python"] == minimum
    assert tool["ruff"]["target-version"] == "py" + minimum.replace(".", "")
    assert tool["pyrefly"]["python-version"] == minimum
    assert tool["pyproject-fmt"]["max_supported_python"] == newest

    # The workflow names no package: it reads the names from the build.
    ci_text = (root / ".github/workflows/ci.yml").read_text()
    ci: dict[str, Any] = yaml.safe_load(ci_text)
    assert ci["env"]["TOOL_PYTHON_VERSION"] == minimum
    assert "DISTRIBUTION_NAME" not in ci["env"]
    assert "example-project" not in ci_text

    docs_enabled = docs == "true"
    assert ("docs" in ci["jobs"]) == docs_enabled
    assert ("pages" in ci["jobs"]) == docs_enabled
    assert ("docs" in ci["jobs"]["ci-gate"]["needs"]) == docs_enabled
    assert (root / "zensical.toml").is_file() == docs_enabled
    assert (root / "docs/site").is_dir() == docs_enabled
    assert ("docs" in hatch) == docs_enabled

    # Computed values aren't stored, so each update recomputes them.
    answers = yaml.safe_load((root / ".copier-answers.yml").read_text())
    for computed in ("supported_python_versions", "minimum_python", "newest_python"):
        assert computed not in answers
    assert (root / "src/example_project/py.typed").is_file()
    assert (root / ".github/dependabot.yml").is_file()
    assert tool["pytest"]["strict"] is True

    # Remote hooks are pinned to commits, with the version in a comment.
    hooks = (root / ".pre-commit-config.yaml").read_text()
    # Hooks run on the oldest supported Python, locally as in CI.
    hook_python = yaml.safe_load(hooks)["default_language_version"]["python"]
    assert hook_python == f"python{minimum}"
    revs = re.findall(r"^    rev: (.*)$", hooks, re.MULTILINE)
    assert revs, "no hook revisions found"
    for rev in revs:
        assert re.fullmatch(r"[0-9a-f]{40}  # frozen: v\d+\.\d+\.\d+", rev), rev


def files(root: Path) -> dict[str, str]:
    """Return the text of every file under root, outside .git, by relative path."""
    return {
        path.relative_to(root).as_posix(): path.read_text()
        for path in sorted(root.rglob("*"))
        if path.is_file() and ".git" not in path.relative_to(root).parts
    }


def test_turning_the_docs_off_with_an_update_matches_a_fresh_render(
    template: Path, tmp_path: Path, git_env: Path
) -> None:
    """The update removes every docs file and section, leaving nothing behind.

    On an unchanged project: in a changed one, turning the docs off also
    conflicts wherever the project edited next to a docs-only section.
    """
    project = render(template, tmp_path / "project", docs_enabled="true")
    for args in (["init", "--quiet", "--initial-branch=main"], ["add", "--all"]):
        subprocess.run(["git", *args], cwd=project, check=True)
    subprocess.run(
        ["git", "commit", "--quiet", "--message", "Generate"], cwd=project, check=True
    )

    copier.run_update(
        project,
        data={"docs_enabled": "false"},
        defaults=True,
        overwrite=True,
        vcs_ref="HEAD",
        quiet=True,
    )

    fresh = render(template, tmp_path / "fresh", docs_enabled="false")
    assert files(project) == files(fresh)
