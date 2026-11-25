"""Compare the GitHub settings of repositories with those of the first one.

Usage: hatch run compare OWNER/REFERENCE OWNER/REPO [OWNER/REPO ...]

Covers the settings configure.py applies, and a few others. A setting that can't
be read, for lack of permission or because the plan doesn't offer it, is shown
as unknown rather than as off. Exits with status 1 if any repository differs
from the reference or any setting is unknown. Needs the GitHub CLI,
signed in as an admin of each repository, because some settings are only
visible to admins.
"""

import argparse
import json
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from _github import GitHub, GitHubError


@dataclass(frozen=True)
class Unknown:
    """A setting that couldn't be read, and why."""

    reason: str


REPOSITORY_FIELDS = (
    "visibility",
    "default_branch",
    "has_issues",
    "has_wiki",
    "has_discussions",
    "has_projects",
    "allow_squash_merge",
    "allow_merge_commit",
    "allow_rebase_merge",
    "allow_auto_merge",
    "squash_merge_commit_title",
    "squash_merge_commit_message",
    "allow_update_branch",
    "delete_branch_on_merge",
    "web_commit_signoff_required",
)

# Fields that differ between otherwise identical rulesets.
RULESET_NOISE = (
    "id",
    "source",
    "source_type",
    "node_id",
    "_links",
    "created_at",
    "updated_at",
    "current_user_can_bypass",
)


def read(github: Any, path: str, *, absent_on_404: Any = Unknown) -> Any:
    """Read from the API, returning Unknown on failure.

    Where GitHub answers 404 to mean "not set", pass the value that means.
    """
    try:
        return github.api(path)
    except GitHubError as error:
        if error.status == 404 and absent_on_404 is not Unknown:
            return absent_on_404
        return Unknown(str(error))


def collect(github: Any, repo: str) -> dict[str, Any]:
    """Return the repository's settings, grouped into sections."""
    settings: dict[str, Any] = {}

    data = read(github, f"repos/{repo}")
    if isinstance(data, Unknown):
        settings["repository"] = data
        settings["security_and_analysis"] = data
    else:
        settings["repository"] = {field: data.get(field) for field in REPOSITORY_FIELDS}
        analysis = data.get("security_and_analysis")
        settings["security_and_analysis"] = (
            {name: value.get("status") for name, value in analysis.items()}
            if analysis is not None
            else Unknown("only visible to repository admins")
        )

    # 204 (no body) means on, 404 means off.
    alerts = read(github, f"repos/{repo}/vulnerability-alerts", absent_on_404=False)
    settings["vulnerability_alerts"] = (
        alerts if isinstance(alerts, Unknown) else alerts is None
    )
    fixes = read(github, f"repos/{repo}/automated-security-fixes", absent_on_404=False)
    settings["automated_security_fixes"] = (
        fixes if isinstance(fixes, Unknown | bool) else fixes.get("enabled")
    )

    pages = read(github, f"repos/{repo}/pages", absent_on_404=None)
    settings["pages"] = (
        {
            "build_type": pages.get("build_type"),
            "https_enforced": pages.get("https_enforced"),
        }
        if isinstance(pages, dict)
        else pages
    )

    actions = read(github, f"repos/{repo}/actions/permissions")
    settings["actions"] = (
        actions
        if isinstance(actions, Unknown)
        else {
            key: actions.get(key)
            for key in ("enabled", "allowed_actions", "sha_pinning_required")
        }
    )
    approval = read(
        github, f"repos/{repo}/actions/permissions/fork-pr-contributor-approval"
    )
    settings["fork_pr_approval"] = (
        approval if isinstance(approval, Unknown) else approval.get("approval_policy")
    )

    settings["rulesets"] = rulesets(github, repo)
    settings["environments"] = environments(github, repo)
    return settings


def rulesets(github: Any, repo: str) -> Any:
    listing = read(github, f"repos/{repo}/rulesets?includes_parents=false&per_page=100")
    if isinstance(listing, Unknown):
        return listing
    result: dict[str, Any] = {}
    for item in listing:
        ruleset = read(github, f"repos/{repo}/rulesets/{item['id']}")
        if isinstance(ruleset, dict):
            for key in RULESET_NOISE:
                ruleset.pop(key, None)
            # Rule order is not meaningful.
            ruleset["rules"] = sorted(
                ruleset.get("rules", []), key=lambda rule: rule["type"]
            )
        result[item["name"]] = ruleset
    return result


def environments(github: Any, repo: str) -> Any:
    listing = read(
        github, f"repos/{repo}/environments", absent_on_404={"environments": []}
    )
    if isinstance(listing, Unknown):
        return listing
    result: dict[str, Any] = {}
    for environment in listing["environments"]:
        name = environment["name"]
        rules = [
            {
                "type": rule.get("type"),
                "prevent_self_review": rule.get("prevent_self_review"),
                "wait_timer": rule.get("wait_timer"),
                "reviewers": sorted(
                    reviewer["reviewer"].get("login")
                    or reviewer["reviewer"].get("name")
                    for reviewer in rule.get("reviewers", [])
                ),
            }
            for rule in environment.get("protection_rules", [])
        ]
        # 404 means the environment has no custom deployment policies.
        policies = read(
            github,
            f"repos/{repo}/environments/{name}/deployment-branch-policies",
            absent_on_404={"branch_policies": []},
        )
        if not isinstance(policies, Unknown):
            policies = sorted(
                (
                    {"name": p["name"], "type": p.get("type")}
                    for p in policies["branch_policies"]
                ),
                key=lambda p: (p["name"], p["type"] or ""),
            )
        result[name] = {
            "deployment_branch_policy": environment.get("deployment_branch_policy"),
            "protection_rules": sorted(rules, key=lambda rule: rule["type"] or ""),
            "policies": policies,
        }
    return result


MISSING = object()


def show(value: Any) -> str:
    if value is MISSING:
        return "(not set)"
    return json.dumps(value, sort_keys=True, separators=(", ", ": "), default=encode)


def diff(a: Any, b: Any, path: str, differences: list[str], unknown: list[str]) -> None:
    """Record where two settings differ, descending into dictionaries."""
    if isinstance(a, Unknown) or isinstance(b, Unknown):
        unknown.append(path)
    elif isinstance(a, dict) and isinstance(b, dict):
        for key in sorted(a.keys() | b.keys()):
            sub_path = f"{path}.{key}" if path else key
            diff(
                a.get(key, MISSING), b.get(key, MISSING), sub_path, differences, unknown
            )
    elif a != b:
        differences.append(f"{path}: {show(a)} -> {show(b)}")


def compare(
    reference: dict[str, Any], other: dict[str, Any]
) -> tuple[list[str], list[str]]:
    """Return the differences and the unknown settings between two repositories."""
    differences: list[str] = []
    unknown: list[str] = []
    diff(reference, other, "", differences, unknown)
    return differences, unknown


def unknown_reasons(settings: dict[str, Any], prefix: str = "") -> list[str]:
    reasons = []
    for key, value in settings.items():
        if isinstance(value, Unknown):
            reasons.append(f"{prefix}{key}: {value.reason}")
        elif isinstance(value, dict):
            reasons.extend(unknown_reasons(value, f"{prefix}{key}."))
    return reasons


def encode(value: Any) -> Any:
    if isinstance(value, Unknown):
        return {"unknown": value.reason}
    raise TypeError(f"can't encode {value!r}")


def main(argv: list[str] | None = None, github: Any = None) -> int:
    parser = argparse.ArgumentParser(
        prog="hatch run compare",
        description="Compare the GitHub settings of repositories with the first one.",
    )
    parser.add_argument("reference", metavar="OWNER/REFERENCE")
    parser.add_argument("repos", metavar="OWNER/REPO", nargs="+")
    args = parser.parse_args(argv)
    if any(repo.count("/") != 1 for repo in [args.reference, *args.repos]):
        parser.error("give each repository as OWNER/REPO")

    github = github or GitHub()
    out = Path(tempfile.mkdtemp(prefix="compare-github-"))
    settings = {}
    for repo in [args.reference, *args.repos]:
        settings[repo] = collect(github, repo)
        path = out / f"{repo.replace('/', '__')}.json"
        path.write_text(
            json.dumps(settings[repo], indent=2, sort_keys=True, default=encode)
        )
        for reason in unknown_reasons(settings[repo]):
            print(f"Unknown in {repo}: {reason}")

    status = 0
    for repo in args.repos:
        print(f"=== {args.reference} vs {repo}")
        differences, unknown = compare(settings[args.reference], settings[repo])
        for line in differences:
            print(line)
        if unknown:
            print(f"Can't compare, as unknown in one or both: {', '.join(unknown)}")
        if not differences and not unknown:
            print("Same settings")
        if differences or unknown:
            status = 1
    print(f"Saved the settings in {out}")
    return status


if __name__ == "__main__":
    sys.exit(main())
