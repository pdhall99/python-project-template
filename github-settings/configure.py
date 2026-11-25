"""Configure the GitHub settings that a project generated from this template needs.

Usage: hatch run configure OWNER/REPO [--no-reviewer] [--dry-run]

Safe to run again: each setting is created or updated in place. Settings GitHub
refuses, such as rulesets on a private repository on GitHub Free, are listed as
not applied, the other settings are still applied, and the script exits with
status 1. Needs the GitHub CLI, signed in as a repository admin.
"""

import argparse
import json
import sys
from collections.abc import Callable
from pathlib import Path
from typing import Any

from _github import GitHub, GitHubError

RULESETS_DIR = Path(__file__).resolve().parent / "rulesets"

# Release tags are X.Y.Z, matching the rulesets and the generated workflow.
TAG_PATTERN = "[0-9]*.[0-9]*.[0-9]*"

REPOSITORY_SETTINGS = {
    "has_wiki": False,
    "has_discussions": False,
    "has_projects": False,
    "allow_squash_merge": True,
    "allow_merge_commit": False,
    "allow_rebase_merge": False,
    "squash_merge_commit_title": "PR_TITLE",
    "squash_merge_commit_message": "BLANK",
    "allow_update_branch": True,
    "delete_branch_on_merge": True,
}


class Configurator:
    """Apply settings one step at a time, recording the steps GitHub refuses."""

    def __init__(self, github: Any, repo: str, *, dry_run: bool) -> None:
        self.github = github
        self.repo = repo
        self.dry_run = dry_run
        self.not_applied: list[str] = []

    def read(self, path: str) -> Any:
        """Read from the API, even in a dry run."""
        return self.github.api(path)

    def write(self, method: str, path: str, body: Any = None) -> None:
        """Change a setting, or print the change in a dry run."""
        if self.dry_run:
            print(f"  would run: {method} {path}")
            if body is not None:
                for line in json.dumps(body, indent=2).splitlines():
                    print(f"    {line}")
        else:
            self.github.api(path, method=method, body=body)

    def refused(self, description: str, error: GitHubError) -> None:
        self.not_applied.append(f"{description} ({error})")
        print(f"Not applied: {description} ({error})")

    def step(self, description: str, apply: Callable[[], str | None]) -> bool:
        """Run one step and return whether it worked.

        The step may return a note to print instead of its description.
        """
        try:
            note = apply()
        except GitHubError as error:
            self.refused(description, error)
            return False
        print(note or description)
        return True


def repository_settings(c: Configurator) -> None:
    c.write("PATCH", f"repos/{c.repo}", REPOSITORY_SETTINGS)


def vulnerability_alerts(c: Configurator) -> None:
    c.write("PUT", f"repos/{c.repo}/vulnerability-alerts")


def security_updates(c: Configurator) -> None:
    c.write("PUT", f"repos/{c.repo}/automated-security-fixes")


def secret_scanning(c: Configurator) -> None:
    enabled = {"status": "enabled"}
    body = {
        "security_and_analysis": {
            "secret_scanning": enabled,
            "secret_scanning_push_protection": enabled,
        }
    }
    c.write("PATCH", f"repos/{c.repo}", body)


def sha_pinning(c: Configurator) -> None:
    body = {"enabled": True, "sha_pinning_required": True}
    c.write("PUT", f"repos/{c.repo}/actions/permissions", body)


def outside_contributor_approval(c: Configurator) -> None:
    body = {"approval_policy": "all_external_contributors"}
    path = f"repos/{c.repo}/actions/permissions/fork-pr-contributor-approval"
    c.write("PUT", path, body)


def pages(c: Configurator) -> str | None:
    try:
        c.read(f"repos/{c.repo}/contents/zensical.toml")
    except GitHubError as error:
        if error.status == 404:
            return "Pages: skipped, as the project has no docs site"
        raise
    try:
        c.read(f"repos/{c.repo}/pages")
    except GitHubError as error:
        if error.status != 404:
            raise
        c.write("POST", f"repos/{c.repo}/pages", {"build_type": "workflow"})
    else:
        c.write("PUT", f"repos/{c.repo}/pages", {"build_type": "workflow"})
    return None


def pypi_environment(c: Configurator, *, reviewer: bool) -> None:
    """Create or update the environment, with your approval for uploads if asked.

    If GitHub refuses the reviewer, nothing changes: an existing environment keeps
    its reviewer, and the step is listed as not applied. Only --no-reviewer
    removes one.
    """
    reviewers = [{"type": "User", "id": c.read("user")["id"]}] if reviewer else []
    branch_policy = {"protected_branches": False, "custom_branch_policies": True}
    body = {"reviewers": reviewers, "deployment_branch_policy": branch_policy}
    c.write("PUT", f"repos/{c.repo}/environments/pypi", body)


def release_tag_policy(c: Configurator) -> str | None:
    """Keep only the release-tag policy, so no branch or other tag can deploy."""
    path = f"repos/{c.repo}/environments/pypi/deployment-branch-policies"
    policies: list[dict[str, Any]]
    try:
        policies = c.read(path)["branch_policies"]
    except GitHubError as error:
        # In a dry run the environment may not exist yet.
        if not (c.dry_run and error.status == 404):
            raise
        policies = []
    have_tag_policy = False
    for policy in policies:
        if policy["type"] == "tag" and policy["name"] == TAG_PATTERN:
            have_tag_policy = True
        else:
            c.write("DELETE", f"{path}/{policy['id']}")
            kind, name = policy["type"], policy["name"]
            print(f"Environment: removed the pypi {kind} policy {name}")
    if not have_tag_policy:
        c.write("POST", path, {"name": TAG_PATTERN, "type": "tag"})
    return None


def ruleset(c: Configurator, file: Path) -> None:
    """Create the ruleset in a JSON file, or replace the one with the same name."""
    body = json.loads(file.read_text())
    existing = c.read(f"repos/{c.repo}/rulesets?includes_parents=false&per_page=100")
    ids = [item["id"] for item in existing if item["name"] == body["name"]]
    if ids:
        c.write("PUT", f"repos/{c.repo}/rulesets/{ids[0]}", body)
    else:
        c.write("POST", f"repos/{c.repo}/rulesets", body)


def configure(github: Any, repo: str, *, reviewer: bool, dry_run: bool) -> list[str]:
    """Apply every setting and return the ones that couldn't be applied."""
    c = Configurator(github, repo, dry_run=dry_run)
    print(f"Configuring {repo}{' (dry run)' if dry_run else ''}")
    c.step(
        "Settings: no wiki, discussions or projects; squash merging with PR titles;"
        " suggest updating PR branches; delete head branches after merge",
        lambda: repository_settings(c),
    )
    c.step("Security: Dependabot alerts", lambda: vulnerability_alerts(c))
    c.step("Security: Dependabot security updates", lambda: security_updates(c))
    c.step("Security: secret scanning and push protection", lambda: secret_scanning(c))
    c.step("Actions: SHA-pinned actions only", lambda: sha_pinning(c))
    c.step(
        "Actions: approve runs for all outside contributors",
        lambda: outside_contributor_approval(c),
    )
    c.step("Pages: deployed from GitHub Actions", lambda: pages(c))
    environment = c.step(
        "Environment: pypi" + (", with your approval" if reviewer else ""),
        lambda: pypi_environment(c, reviewer=reviewer),
    )
    if environment:
        c.step("Environment: pypi, release tags only", lambda: release_tag_policy(c))
    elif reviewer:
        print(
            "  GitHub Free allows required reviewers only on public repositories."
            " To set up the environment without your approval, run again with --no-reviewer."
        )
    for file in sorted(RULESETS_DIR.glob("*.json")):
        name = json.loads(file.read_text())["name"]
        c.step(f"Ruleset: {name}", lambda file=file: ruleset(c, file))
    return c.not_applied


def main(argv: list[str] | None = None, github: Any = None) -> int:
    parser = argparse.ArgumentParser(
        prog="hatch run configure",
        description="Configure the GitHub settings for a generated project.",
    )
    parser.add_argument("repo", metavar="OWNER/REPO")
    parser.add_argument(
        "--no-reviewer",
        action="store_true",
        help="don't require your approval before each PyPI upload",
    )
    parser.add_argument("--dry-run", action="store_true", help="print the changes only")
    args = parser.parse_args(argv)
    if args.repo.count("/") != 1:
        parser.error("give the repository as OWNER/REPO")

    not_applied = configure(
        github or GitHub(),
        args.repo,
        reviewer=not args.no_reviewer,
        dry_run=args.dry_run,
    )
    owner, name = args.repo.split("/")
    print(
        "\nOne setting is on PyPI, not GitHub: add a trusted publisher at"
        "\nhttps://pypi.org/manage/account/publishing/ (a pending publisher for a"
        f" new project)\nwith owner {owner}, repository {name}, workflow ci.yml"
        " and environment pypi."
    )
    if not_applied:
        print(f"\n{len(not_applied)} settings were not applied:", file=sys.stderr)
        for item in not_applied:
            print(f"- {item}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
