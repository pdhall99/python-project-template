"""Create a project from this template, push it to a new GitHub repository and
configure that repository.

Usage: hatch run new-project DIRECTORY [--private] [--no-reviewer] [--vcs-ref REF]

Copies the template from GitHub rather than from this clone, so the project's
.copier-answers.yml points at GitHub. --vcs-ref copies a branch, tag or commit
other than the latest release, for example to try an unreleased change.

If DIRECTORY already holds a generated project, the copy is skipped, and any other
step that's already done is skipped too, so the script can be run again after a
failure. If DIRECTORY is inside another Git repository's working tree, it gets a
repository of its own, so the outer one is never committed to or pushed. The
script refuses to continue if origin, or any URL it pushes to, points somewhere
else, or if an existing GitHub repository's visibility isn't the one asked for.

Needs Git, Hatch and the GitHub CLI. On GitHub Free, rulesets and the
environment reviewer need a public repository: configure.py reports any setting
GitHub refuses, and this script then exits with status 1.
"""

import argparse
import re
import shutil
import subprocess
import sys
from pathlib import Path

import yaml

# Change this in a fork.
TEMPLATE = "gh:pdhall99/python-project-template"

CONFIGURE = Path(__file__).resolve().parent / "github-settings" / "configure.py"
BRANCH = "main"


class SetupError(Exception):
    """A problem that stops the setup, with a message for the user."""


def run(*args: str | Path, cwd: Path | None = None) -> str:
    """Run a command, returning its output; raise SetupError if it fails."""
    result = subprocess.run(
        [str(arg) for arg in args], cwd=cwd, capture_output=True, text=True, check=False
    )
    if result.returncode != 0:
        command = " ".join(str(arg) for arg in args)
        raise SetupError(f"{command} failed:\n{result.stderr.strip()}")
    return result.stdout.strip()


def succeeds(*args: str | Path, cwd: Path | None = None) -> bool:
    result = subprocess.run(
        [str(arg) for arg in args], cwd=cwd, capture_output=True, check=False
    )
    return result.returncode == 0


def github_repo(url: str) -> str | None:
    """Return the OWNER/REPO a GitHub remote URL points to, or None."""
    match = re.fullmatch(
        r"(?:https://github\.com/|git@github\.com:|ssh://git@github\.com/)"
        r"([^/]+/[^/]+?)(?:\.git)?/?",
        url.strip(),
    )
    return match.group(1) if match else None


def read_answers(directory: Path) -> tuple[str, str, str]:
    """Return the owner, project name and description from the Copier answers."""
    answers = yaml.safe_load((directory / ".copier-answers.yml").read_text())
    return (
        str(answers["github_owner"]),
        str(answers["project_name"]),
        str(answers["project_description"]),
    )


def copy_template(directory: Path, vcs_ref: str | None) -> None:
    if (directory / ".copier-answers.yml").is_file():
        print(f"Using the existing project in {directory}")
        return
    if directory.exists() and any(directory.iterdir()):
        raise SetupError(f"{directory} exists and is not a generated project")
    ref = ["--vcs-ref", vcs_ref] if vcs_ref else []
    # Copier from this environment, at the version pinned in pyproject.toml.
    # Not captured: Copier asks its questions here.
    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "copier",
            "copy",
            "--quiet",
            *ref,
            TEMPLATE,
            str(directory),
        ],
        check=False,
    )
    if result.returncode != 0:
        raise SetupError("copier copy failed")


def ensure_git_repo(directory: Path) -> None:
    """Make the directory its own Git repository, with a first commit on main.

    Git looks for a repository in parent directories too, so a project inside
    another repository's working tree gets a repository of its own, rather than
    the outer one being used.
    """
    directory = directory.resolve()
    top = None
    if succeeds("git", "-C", directory, "rev-parse", "--show-toplevel"):
        top = Path(
            run("git", "-C", directory, "rev-parse", "--show-toplevel")
        ).resolve()
    if top != directory:
        run("git", "-C", directory, "init", "--quiet", f"--initial-branch={BRANCH}")
        print(f"Git: created a repository in {directory}")
    # Before committing, so a repository on another branch gets no commit.
    # symbolic-ref works before the first commit too.
    branch = run("git", "-C", directory, "symbolic-ref", "--short", "HEAD")
    if branch != BRANCH:
        raise SetupError(f"{directory} is on branch {branch}, not {BRANCH}")
    if succeeds("git", "-C", directory, "rev-parse", "--verify", "--quiet", "HEAD"):
        print("Git: the project already has commits")
    else:
        run("git", "-C", directory, "add", "--all")
        run(
            "git", "-C", directory, "commit", "--quiet",
            "--message", "Create project from python-project-template",
        )  # fmt: skip
        print("Git: committed the project")


def check_origin(directory: Path, repo: str) -> bool:
    """Return whether there's an origin remote, checking it points to the repo.

    Checks its fetch URL and any separate push URLs, as configured: insteadOf
    rewriting, such as from HTTPS to SSH, is the user's own Git configuration.
    Run before anything changes on GitHub, so a wrong origin stops the setup first.
    """
    urls: list[str] = []
    for key in ("remote.origin.url", "remote.origin.pushurl"):
        if succeeds("git", "-C", directory, "config", "--get-all", key):
            urls += run("git", "-C", directory, "config", "--get-all", key).splitlines()
    for url in urls:
        points_to = github_repo(url)
        if points_to is None or points_to.lower() != repo.lower():
            raise SetupError(f"origin points to {url}, not to {repo}")
    return bool(urls)


def add_origin(directory: Path, repo: str, protocol: str) -> None:
    url = (
        f"git@github.com:{repo}.git"
        if protocol == "ssh"
        else f"https://github.com/{repo}.git"
    )
    run("git", "-C", directory, "remote", "add", "origin", url)


def ensure_github_repo(repo: str, *, private: bool) -> None:
    visibility = "private" if private else "public"
    if succeeds("gh", "repo", "view", repo):
        actual = run(
            "gh", "repo", "view", repo, "--json", "visibility", "--jq", ".visibility"
        )
        if actual.lower() != visibility:
            flag = "--private" if actual.lower() == "private" else "no --private"
            raise SetupError(
                f"{repo} is {actual.lower()}, not {visibility}: change its visibility on"
                f" GitHub, or run again with {flag}"
            )
        print(f"GitHub: {repo} already exists")
    else:
        run("gh", "repo", "create", repo, f"--{visibility}")
        print(f"GitHub: created {repo} ({visibility})")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="hatch run new-project",
        description="Create a project, push it to a new GitHub repository and configure it.",
    )
    parser.add_argument("directory", type=Path)
    parser.add_argument(
        "--private", action="store_true", help="create a private repository"
    )
    parser.add_argument(
        "--no-reviewer",
        action="store_true",
        help="don't require your approval before each PyPI upload",
    )
    parser.add_argument(
        "--vcs-ref",
        help="the template branch, tag or commit to copy, instead of the latest",
    )
    args = parser.parse_args(argv)

    try:
        for tool in ("git", "hatch", "gh"):
            if shutil.which(tool) is None:
                raise SetupError(f"needs {tool}")
        if not succeeds("gh", "auth", "status"):
            raise SetupError("sign in to GitHub first, with gh auth login")

        # 1. Copy the template.
        directory: Path = args.directory
        copy_template(directory, args.vcs_ref)
        owner, name, description = read_answers(directory)
        repo = f"{owner}/{name}"

        # 2. Commit the project, which Hatch-VCS needs to work out the version,
        # and install the pre-commit hooks.
        ensure_git_repo(directory)
        has_origin = check_origin(directory, repo)
        run("hatch", "run", "pre-commit:install", cwd=directory)
        print("Git: installed the pre-commit hooks")

        # 3. Create the GitHub repository and push to it, with the project's
        # description, as standard-readme asks.
        ensure_github_repo(repo, private=args.private)
        if not has_origin:
            add_origin(directory, repo, run("gh", "config", "get", "git_protocol"))
        run(
            "git",
            "-C",
            directory,
            "push",
            "--quiet",
            "--set-upstream",
            "origin",
            BRANCH,
        )
        print(f"GitHub: pushed {BRANCH}")
        run("gh", "repo", "edit", repo, "--description", description)
        print("GitHub: description set to the project description")
    except SetupError as error:
        print(f"new-project.py: {error}", file=sys.stderr)
        return 1

    # 4. Configure the repository. It prints the PyPI step that remains.
    print()
    configure_args = [repo] + (["--no-reviewer"] if args.no_reviewer else [])
    status = subprocess.run(
        [sys.executable, str(CONFIGURE), *configure_args], check=False
    ).returncode
    print(f"\nCreated {repo} in {directory}")
    return status


if __name__ == "__main__":
    sys.exit(main())
