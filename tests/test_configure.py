"""Tests for github-settings/configure.py."""

import json
from pathlib import Path
from typing import Any

import pytest

from _github import GitHubError
from conftest import ROOT, FakeGitHub, load_script

configure = load_script(ROOT / "github-settings" / "configure.py", "configure")

REPO = "owner/demo"
POLICIES = f"repos/{REPO}/environments/pypi/deployment-branch-policies"
RULESETS = f"repos/{REPO}/rulesets?includes_parents=false&per_page=100"


def responses(**overrides: Any) -> dict[tuple[str, str], Any]:
    """Responses for a public repository with no docs site and nothing set up yet."""
    table: dict[tuple[str, str], Any] = {
        ("GET", "user"): {"id": 42},
        ("GET", f"repos/{REPO}/contents/zensical.toml"): GitHubError("Not Found", 404),
        ("GET", POLICIES): {"branch_policies": []},
        ("GET", RULESETS): [],
    }
    for key, value in overrides.items():
        method, _, path = key.partition(" ")
        table[(method, path)] = value
    return table


def test_applies_every_setting_to_a_new_public_repository(
    capsys: pytest.CaptureFixture[str],
) -> None:
    github = FakeGitHub(responses())

    assert configure.main([REPO], github=github) == 0

    assert github.writes() == [
        ("PATCH", f"repos/{REPO}"),
        ("PUT", f"repos/{REPO}/vulnerability-alerts"),
        ("PUT", f"repos/{REPO}/automated-security-fixes"),
        ("PATCH", f"repos/{REPO}"),
        ("PUT", f"repos/{REPO}/actions/permissions"),
        ("PUT", f"repos/{REPO}/actions/permissions/fork-pr-contributor-approval"),
        ("PUT", f"repos/{REPO}/environments/pypi"),
        ("POST", POLICIES),
        ("POST", f"repos/{REPO}/rulesets"),
        ("POST", f"repos/{REPO}/rulesets"),
    ]
    environment = next(
        body for method, path, body in github.calls if path.endswith("/pypi")
    )
    assert environment["reviewers"] == [{"type": "User", "id": 42}]
    policy = next(
        body
        for method, path, body in github.calls
        if (method, path) == ("POST", POLICIES)
    )
    assert policy == {"name": "[0-9]*.[0-9]*.[0-9]*", "type": "tag"}
    output = capsys.readouterr().out
    assert "Pages: skipped, as the project has no docs site" in output
    assert "Not applied" not in output


def test_reports_settings_github_refuses_and_applies_the_rest(
    capsys: pytest.CaptureFixture[str],
) -> None:
    upgrade = GitHubError("Upgrade to GitHub Pro or make this repository public", 403)

    def environment(body: dict[str, Any]) -> Any:
        return (
            GitHubError("Reviewers need GitHub Pro", 422) if body["reviewers"] else None
        )

    def settings(body: dict[str, Any]) -> Any:
        if "security_and_analysis" in body:
            return GitHubError("Secret scanning is not available", 422)
        return None

    github = FakeGitHub(
        responses(
            **{
                f"PATCH repos/{REPO}": settings,
                f"PUT repos/{REPO}/environments/pypi": environment,
                f"GET {RULESETS}": upgrade,
            }
        )
    )

    assert configure.main([REPO], github=github) == 1

    writes = github.writes()
    # The steps after each refusal still ran.
    assert ("PUT", f"repos/{REPO}/actions/permissions") in writes
    assert ("POST", f"repos/{REPO}/rulesets") not in writes
    captured = capsys.readouterr()
    assert "run again with --no-reviewer" in captured.out
    assert "4 settings were not applied" in captured.err
    for item in (
        "secret scanning",
        "Environment: pypi, with your approval",
        "Ruleset: main",
        "Ruleset: release tags",
    ):
        assert item in captured.err


def test_never_removes_a_reviewer_github_refuses() -> None:
    """A refused or failed reviewer must not weaken an existing environment."""
    refused = GitHubError("Service unavailable", 503)
    github = FakeGitHub(responses(**{f"PUT repos/{REPO}/environments/pypi": refused}))

    assert configure.main([REPO], github=github) == 1

    environment_writes = [
        body
        for method, path, body in github.calls
        if path.endswith("/environments/pypi")
    ]
    assert environment_writes == [
        {
            "reviewers": [{"type": "User", "id": 42}],
            "deployment_branch_policy": {
                "protected_branches": False,
                "custom_branch_policies": True,
            },
        }
    ]
    # The release-tag policy depends on the environment, so it isn't touched.
    assert ("POST", POLICIES) not in github.writes()


def test_dry_run_changes_nothing(capsys: pytest.CaptureFixture[str]) -> None:
    github = FakeGitHub(responses())

    assert configure.main([REPO, "--dry-run"], github=github) == 0

    assert github.writes() == []
    assert f"would run: PATCH repos/{REPO}" in capsys.readouterr().out


def test_dry_run_works_before_the_environment_exists() -> None:
    github = FakeGitHub(responses(**{f"GET {POLICIES}": GitHubError("Not Found", 404)}))

    assert configure.main([REPO, "--dry-run"], github=github) == 0


def test_keeps_only_the_release_tag_policy() -> None:
    policies = [
        {"id": 1, "type": "branch", "name": "main"},
        {"id": 2, "type": "tag", "name": "[0-9]*.[0-9]*.[0-9]*"},
        {"id": 3, "type": "tag", "name": "*"},
    ]
    github = FakeGitHub(responses(**{f"GET {POLICIES}": {"branch_policies": policies}}))

    assert configure.main([REPO], github=github) == 0

    writes = github.writes()
    assert ("DELETE", f"{POLICIES}/1") in writes
    assert ("DELETE", f"{POLICIES}/3") in writes
    assert ("DELETE", f"{POLICIES}/2") not in writes
    assert ("POST", POLICIES) not in writes


def test_replaces_rulesets_with_the_same_name() -> None:
    github = FakeGitHub(responses(**{f"GET {RULESETS}": [{"id": 7, "name": "main"}]}))

    assert configure.main([REPO], github=github) == 0

    writes = github.writes()
    assert ("PUT", f"repos/{REPO}/rulesets/7") in writes
    assert writes.count(("POST", f"repos/{REPO}/rulesets")) == 1


@pytest.mark.parametrize(
    ("pages", "method"),
    [(GitHubError("Not Found", 404), "POST"), ({"build_type": "legacy"}, "PUT")],
    ids=["new", "existing"],
)
def test_sets_up_pages_for_a_docs_site(pages: Any, method: str) -> None:
    github = FakeGitHub(
        responses(
            **{
                f"GET repos/{REPO}/contents/zensical.toml": {"name": "zensical.toml"},
                f"GET repos/{REPO}/pages": pages,
            }
        )
    )

    assert configure.main([REPO], github=github) == 0

    assert (method, f"repos/{REPO}/pages") in github.writes()


def test_no_reviewer() -> None:
    github = FakeGitHub(responses())

    assert configure.main([REPO, "--no-reviewer"], github=github) == 0

    environment = next(
        body for method, path, body in github.calls if path.endswith("/pypi")
    )
    assert environment["reviewers"] == []


def test_rejects_a_repository_without_an_owner() -> None:
    with pytest.raises(SystemExit) as exit_info:
        configure.main(["demo"], github=FakeGitHub())
    assert exit_info.value.code == 2


RULESET_FILES = sorted((ROOT / "github-settings" / "rulesets").glob("*.json"))


@pytest.mark.parametrize("file", RULESET_FILES, ids=[f.name for f in RULESET_FILES])
def test_rulesets_are_json_with_names(file: Path) -> None:
    assert json.loads(file.read_text())["name"]
