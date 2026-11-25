"""Call the GitHub REST API through the GitHub CLI, so its sign-in is reused."""

import json
import re
import subprocess
from typing import Any


class GitHubError(Exception):
    """A failed GitHub API request, with its HTTP status if there was one."""

    def __init__(self, message: str, status: int | None = None) -> None:
        super().__init__(message if status is None else f"HTTP {status}: {message}")
        self.message = message
        self.status = status


class GitHub:
    """Make GitHub API requests with `gh api`."""

    def api(self, path: str, method: str = "GET", body: Any = None) -> Any:
        """Return the decoded response, or None for an empty one.

        Raises GitHubError if the request fails. A failed `gh api` call prints the
        response body to stdout and the status to stderr, so read both.
        """
        args = ["gh", "api", path, "--method", method]
        stdin = None
        if body is not None:
            args += ["--input", "-"]
            stdin = json.dumps(body)
        result = subprocess.run(
            args, input=stdin, capture_output=True, text=True, check=False
        )
        if result.returncode != 0:
            raise _error(result.stdout, result.stderr)
        if not result.stdout.strip():
            return None
        return json.loads(result.stdout)


def _error(stdout: str, stderr: str) -> GitHubError:
    status = None
    if match := re.search(r"\(HTTP (\d{3})\)", stderr):
        status = int(match.group(1))
    try:
        message = json.loads(stdout)["message"]
    except (ValueError, KeyError, TypeError):
        message = stderr.strip().removeprefix("gh: ") or "the request failed"
    return GitHubError(message, status)
