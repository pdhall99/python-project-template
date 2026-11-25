"""Tests for github-settings/compare.py."""

from typing import Any

import pytest

from _github import GitHubError
from conftest import ROOT, FakeGitHub, load_script

compare = load_script(ROOT / "github-settings" / "compare.py", "compare")

TAG = "[0-9]*.[0-9]*.[0-9]*"


def responses(repo: str, **overrides: Any) -> dict[tuple[str, str], Any]:
    """Responses for a repository configured as configure.py leaves it."""
    table: dict[tuple[str, str], Any] = {
        ("GET", f"repos/{repo}"): {
            "visibility": "public",
            "has_wiki": False,
            "allow_squash_merge": True,
            "security_and_analysis": {"secret_scanning": {"status": "enabled"}},
        },
        ("GET", f"repos/{repo}/vulnerability-alerts"): None,
        ("GET", f"repos/{repo}/automated-security-fixes"): {
            "enabled": True,
            "paused": False,
        },
        ("GET", f"repos/{repo}/pages"): GitHubError("Not Found", 404),
        ("GET", f"repos/{repo}/actions/permissions"): {
            "enabled": True,
            "allowed_actions": "all",
            "sha_pinning_required": True,
        },
        ("GET", f"repos/{repo}/actions/permissions/fork-pr-contributor-approval"): {
            "approval_policy": "all_external_contributors"
        },
        ("GET", f"repos/{repo}/rulesets?includes_parents=false&per_page=100"): [
            {"id": 1, "name": "main"}
        ],
        ("GET", f"repos/{repo}/rulesets/1"): {
            "id": 1,
            "name": "main",
            "rules": [{"type": "pull_request"}, {"type": "deletion"}],
        },
        ("GET", f"repos/{repo}/environments"): {
            "environments": [
                {
                    "name": "pypi",
                    "deployment_branch_policy": {"custom_branch_policies": True},
                    "protection_rules": [
                        {
                            "type": "required_reviewers",
                            "reviewers": [{"reviewer": {"login": "me"}}],
                        }
                    ],
                }
            ]
        },
        ("GET", f"repos/{repo}/environments/pypi/deployment-branch-policies"): {
            "branch_policies": [{"id": 9, "name": TAG, "type": "tag"}]
        },
    }
    for key, value in overrides.items():
        table[("GET", f"repos/{repo}{key}")] = value
    return table


def run(*tables: dict[tuple[str, str], Any]) -> int:
    merged: dict[tuple[str, str], Any] = {}
    for table in tables:
        merged.update(table)
    return compare.main(["owner/a", "owner/b"], github=FakeGitHub(merged))


def test_same_settings(capsys: pytest.CaptureFixture[str]) -> None:
    assert run(responses("owner/a"), responses("owner/b")) == 0
    assert "Same settings" in capsys.readouterr().out


def test_ignores_rule_order_and_ruleset_ids() -> None:
    reordered = {
        "/rulesets?includes_parents=false&per_page=100": [{"id": 5, "name": "main"}],
        "/rulesets/5": {
            "id": 5,
            "name": "main",
            "rules": [{"type": "deletion"}, {"type": "pull_request"}],
        },
    }
    assert run(responses("owner/a"), responses("owner/b", **reordered)) == 0


def test_reports_differences(capsys: pytest.CaptureFixture[str]) -> None:
    other = responses(
        "owner/b", **{"/pages": {"build_type": "workflow", "https_enforced": True}}
    )

    assert run(responses("owner/a"), other) == 1

    output = capsys.readouterr().out
    assert 'pages: null -> {"build_type": "workflow", "https_enforced": true}' in output


def test_treats_404_as_off_where_github_means_off(
    capsys: pytest.CaptureFixture[str],
) -> None:
    other = responses(
        "owner/b", **{"/vulnerability-alerts": GitHubError("Not Found", 404)}
    )

    assert run(responses("owner/a"), other) == 1

    assert "vulnerability_alerts: true -> false" in capsys.readouterr().out


def test_settings_that_cant_be_read_are_unknown_not_equal(
    capsys: pytest.CaptureFixture[str],
) -> None:
    """Two repositories whose rulesets can't be read must not count as the same."""
    refused = {
        "/rulesets?includes_parents=false&per_page=100": GitHubError(
            "Upgrade to GitHub Pro", 403
        )
    }

    assert run(responses("owner/a", **refused), responses("owner/b", **refused)) == 1

    output = capsys.readouterr().out
    assert "Unknown in owner/a: rulesets: HTTP 403: Upgrade to GitHub Pro" in output
    assert "Can't compare, as unknown in one or both: rulesets" in output
    assert "Same settings" not in output


def test_security_settings_are_unknown_without_admin_access(
    capsys: pytest.CaptureFixture[str],
) -> None:
    hidden = {
        "": {"visibility": "public", "has_wiki": False, "allow_squash_merge": True}
    }

    assert run(responses("owner/a"), responses("owner/b", **hidden)) == 1

    assert "security_and_analysis" in capsys.readouterr().out


def test_saves_each_repository_with_unknowns_marked(
    capsys: pytest.CaptureFixture[str],
) -> None:
    refused = {"/environments": GitHubError("Forbidden", 403)}
    run(responses("owner/a"), responses("owner/b", **refused))

    saved = capsys.readouterr().out.rsplit("Saved the settings in ", 1)[1].strip()
    text = (compare.Path(saved) / "owner__b.json").read_text()
    assert '"unknown": "HTTP 403: Forbidden"' in text


def test_reports_an_environment_only_one_has_even_if_partly_unknown(
    capsys: pytest.CaptureFixture[str],
) -> None:
    """A difference whose value contains an unknown setting can still be shown."""
    refused = {
        "/environments/pypi/deployment-branch-policies": GitHubError("Forbidden", 403)
    }
    none: dict[str, Any] = {"/environments": {"environments": []}}

    assert run(responses("owner/a", **refused), responses("owner/b", **none)) == 1

    output = capsys.readouterr().out
    assert 'environments.pypi: {"deployment_branch_policy"' in output
    assert '"policies": {"unknown": "HTTP 403: Forbidden"}' in output
    assert "-> (not set)" in output
