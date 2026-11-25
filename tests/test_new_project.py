"""Tests for new-project.py.

GitHub, Hatch and configure.py are replaced by fakes that log their arguments. Git
is real: pushes to the GitHub URL go to a local bare repository instead, through
Git's insteadOf setting.
"""

import os
import subprocess
import sys
from pathlib import Path

import pytest

from conftest import ROOT, load_script

new_project = load_script(ROOT / "new-project.py", "new_project")

REPO = "owner/demo"
DESCRIPTION = 'A demo: with "quotes"'

FAKE_GH = """#!/usr/bin/env bash
echo "$*" >> "$FAKES/gh.log"
case "$1 $2" in
  "auth status") exit 0 ;;
  "repo view")
    [[ -f "$FAKES/repo-exists" ]] || exit 1
    [[ "$*" == *--json* ]] && echo PUBLIC
    exit 0 ;;
  "repo create") touch "$FAKES/repo-exists" ;;
  "config get") echo https ;;
esac
"""

FAKE_HATCH = """#!/usr/bin/env bash
echo "$*" >> "$FAKES/hatch.log"
"""

FAKE_CONFIGURE = """import os, sys
with open(os.path.join(os.environ["FAKES"], "configure.log"), "a") as log:
    print(" ".join(sys.argv[1:]), file=log)
sys.exit(int(os.environ.get("FAKE_CONFIGURE_STATUS", "0")))
"""


def git(*args: str | Path, cwd: Path) -> str:
    return subprocess.run(
        ["git", *map(str, args)], cwd=cwd, capture_output=True, text=True, check=True
    ).stdout.strip()


@pytest.fixture
def fakes(tmp_path: Path, git_env: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Put fake gh and hatch on PATH, fake configure.py, and push to a local repository."""
    fakes = tmp_path / "fakes"
    (fakes / "bin").mkdir(parents=True)
    for name, script in {"gh": FAKE_GH, "hatch": FAKE_HATCH}.items():
        path = fakes / "bin" / name
        path.write_text(script)
        path.chmod(0o755)
    (fakes / "configure.py").write_text(FAKE_CONFIGURE)
    monkeypatch.setattr(new_project, "CONFIGURE", fakes / "configure.py")
    monkeypatch.setenv("FAKES", str(fakes))
    monkeypatch.setenv("PATH", f"{fakes / 'bin'}{os.pathsep}{os.environ['PATH']}")

    remote = tmp_path / "remote.git"
    subprocess.run(["git", "init", "--quiet", "--bare", str(remote)], check=True)
    with git_env.open("a") as config:
        config.write(f'[url "{remote}"]\n\tinsteadOf = https://github.com/{REPO}.git\n')
    return fakes


def make_project(directory: Path) -> Path:
    """Write a minimal generated project, so no copy is needed."""
    directory.mkdir(parents=True)
    (directory / ".copier-answers.yml").write_text(
        "github_owner: owner\nproject_name: demo\nproject_description: 'A demo: with \"quotes\"'\n"
    )
    (directory / "README.md").write_text("# demo\n")
    return directory


def log(fakes: Path, name: str) -> str:
    path = fakes / f"{name}.log"
    return path.read_text() if path.exists() else ""


def test_creates_pushes_and_configures(tmp_path: Path, fakes: Path) -> None:
    project = make_project(tmp_path / "demo")

    assert new_project.main([str(project)]) == 0

    remote_log = git("log", "--format=%s", "main", cwd=tmp_path / "remote.git")
    assert remote_log == "Create project from python-project-template"
    gh = log(fakes, "gh")
    assert f"repo create {REPO} --public" in gh
    assert f"repo edit {REPO} --description {DESCRIPTION}" in gh
    assert "run pre-commit:install" in log(fakes, "hatch")
    assert log(fakes, "configure") == f"{REPO}\n"


def test_running_again_skips_what_is_done(tmp_path: Path, fakes: Path) -> None:
    project = make_project(tmp_path / "demo")
    assert new_project.main([str(project)]) == 0
    (fakes / "gh.log").unlink()

    assert new_project.main([str(project)]) == 0

    assert git("rev-list", "--count", "HEAD", cwd=project) == "1"
    assert "repo create" not in log(fakes, "gh")


def test_a_project_inside_another_repository_gets_its_own(
    tmp_path: Path, fakes: Path
) -> None:
    """The outer repository must be neither committed to nor pushed."""
    outer = tmp_path / "outer"
    outer.mkdir()
    git("init", "--quiet", "--initial-branch=main", cwd=outer)
    (outer / "private.txt").write_text("not for GitHub\n")
    git("add", "--all", cwd=outer)
    git("commit", "--quiet", "--message", "Outer commit", cwd=outer)
    project = make_project(outer / "demo")

    assert new_project.main([str(project)]) == 0

    assert (project / ".git").is_dir()
    assert git("log", "--format=%s", cwd=outer) == "Outer commit"
    pushed = git("log", "--format=%s", "main", cwd=tmp_path / "remote.git")
    assert pushed == "Create project from python-project-template"
    files = git("ls-tree", "-r", "--name-only", "main", cwd=tmp_path / "remote.git")
    assert "private.txt" not in files


def test_refuses_an_origin_that_points_elsewhere(
    tmp_path: Path, fakes: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    project = make_project(tmp_path / "demo")
    git("init", "--quiet", "--initial-branch=main", cwd=project)
    git("remote", "add", "origin", "git@github.com:someone/else.git", cwd=project)

    assert new_project.main([str(project)]) == 1

    assert "origin points to git@github.com:someone/else.git, not to owner/demo" in (
        capsys.readouterr().err
    )
    assert git("for-each-ref", cwd=tmp_path / "remote.git") == ""
    assert "repo create" not in log(fakes, "gh")


def test_refuses_a_push_url_that_points_elsewhere(
    tmp_path: Path, fakes: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    project = make_project(tmp_path / "demo")
    git("init", "--quiet", "--initial-branch=main", cwd=project)
    git("remote", "add", "origin", f"https://github.com/{REPO}.git", cwd=project)
    git(
        "remote",
        "set-url",
        "--push",
        "origin",
        "git@github.com:someone/else.git",
        cwd=project,
    )

    assert new_project.main([str(project)]) == 1

    assert "origin points to git@github.com:someone/else.git" in capsys.readouterr().err
    assert "repo create" not in log(fakes, "gh")


def test_refuses_an_existing_repository_with_the_other_visibility(
    tmp_path: Path, fakes: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """Asked for a private repository, never push to an existing public one."""
    (fakes / "repo-exists").touch()  # The fake reports it as public.
    project = make_project(tmp_path / "demo")

    assert new_project.main([str(project), "--private"]) == 1

    assert "owner/demo is public, not private" in capsys.readouterr().err
    assert git("for-each-ref", cwd=tmp_path / "remote.git") == ""


def test_refuses_a_branch_other_than_main_before_committing(
    tmp_path: Path, fakes: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    project = make_project(tmp_path / "demo")
    git("init", "--quiet", "--initial-branch=work", cwd=project)

    assert new_project.main([str(project)]) == 1

    assert "is on branch work, not main" in capsys.readouterr().err
    assert git("for-each-ref", cwd=project) == ""


def test_refuses_a_folder_that_isnt_a_project(
    tmp_path: Path, fakes: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    folder = tmp_path / "notes"
    folder.mkdir()
    (folder / "notes.txt").write_text("")

    assert new_project.main([str(folder)]) == 1

    assert "exists and is not a generated project" in capsys.readouterr().err


def test_passes_on_configure_failures(
    tmp_path: Path, fakes: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("FAKE_CONFIGURE_STATUS", "1")
    project = make_project(tmp_path / "demo")

    assert new_project.main([str(project), "--private", "--no-reviewer"]) == 1

    assert f"repo create {REPO} --private" in log(fakes, "gh")
    assert log(fakes, "configure") == f"{REPO} --no-reviewer\n"


@pytest.mark.parametrize(
    ("url", "repo"),
    [
        ("https://github.com/owner/demo.git", "owner/demo"),
        ("https://github.com/owner/demo", "owner/demo"),
        ("git@github.com:owner/demo.git", "owner/demo"),
        ("ssh://git@github.com/owner/demo.git", "owner/demo"),
        ("https://gitlab.com/owner/demo.git", None),
        ("/some/local/path", None),
    ],
)
def test_github_repo(url: str, repo: str | None) -> None:
    assert new_project.github_repo(url) == repo


@pytest.mark.parametrize(
    ("vcs_ref", "expected"), [(None, []), ("some-branch", ["--vcs-ref", "some-branch"])]
)
def test_copies_the_template_with_this_environments_copier(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    vcs_ref: str | None,
    expected: list[str],
) -> None:
    calls: list[list[str]] = []

    def run(args: list[str], **_: object) -> subprocess.CompletedProcess[str]:
        calls.append(args)
        return subprocess.CompletedProcess(args, 0)

    monkeypatch.setattr(new_project.subprocess, "run", run)
    new_project.copy_template(tmp_path / "demo", vcs_ref)

    assert calls == [
        [
            sys.executable,
            "-m",
            "copier",
            "copy",
            "--quiet",
            *expected,
            new_project.TEMPLATE,
            str(tmp_path / "demo"),
        ]
    ]
