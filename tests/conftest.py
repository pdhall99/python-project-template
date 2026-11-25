"""Shared helpers for testing the repository's scripts."""

import importlib.util
import sys
from collections.abc import Callable
from pathlib import Path
from types import ModuleType
from typing import Any

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "github-settings"))

from _github import GitHubError  # noqa: E402


def load_script(path: Path, name: str) -> ModuleType:
    """Import a script whose file name isn't a valid module name."""
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


class FakeGitHub:
    """Answer API requests from a table, recording every request.

    A response is a value to return, a GitHubError to raise, or a function of the
    request body returning either. Requests not in the table get None.
    """

    def __init__(self, responses: dict[tuple[str, str], Any] | None = None) -> None:
        self.responses = responses or {}
        self.calls: list[tuple[str, str, Any]] = []

    def api(self, path: str, method: str = "GET", body: Any = None) -> Any:
        self.calls.append((method, path, body))
        response = self.responses.get((method, path))
        if isinstance(response, Callable):
            response = response(body)
        if isinstance(response, GitHubError):
            raise response
        return response

    def writes(self) -> list[tuple[str, str]]:
        return [(method, path) for method, path, _ in self.calls if method != "GET"]


@pytest.fixture
def git_env(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Isolate Git from the user's configuration, returning the global config file."""
    config = tmp_path / "gitconfig"
    config.write_text("")
    monkeypatch.setenv("GIT_CONFIG_GLOBAL", str(config))
    monkeypatch.setenv("GIT_CONFIG_NOSYSTEM", "1")
    for role in ("AUTHOR", "COMMITTER"):
        monkeypatch.setenv(f"GIT_{role}_NAME", "Test")
        monkeypatch.setenv(f"GIT_{role}_EMAIL", "test@example.com")
    return config
