from __future__ import annotations

import pytest

from agent.poller_main import validate_poller_config
from agent.pollers.github import build_issue_comment_payload, parse_github_poll_repos


def test_parse_github_poll_repos_accepts_comma_separated_repos() -> None:
    assert parse_github_poll_repos("owner/repo, other/second") == [
        ("owner", "repo"),
        ("other", "second"),
    ]


def test_parse_github_poll_repos_rejects_repo_without_owner() -> None:
    with pytest.raises(ValueError, match="Expected owner/repo"):
        parse_github_poll_repos("repo-only")


def test_validate_poller_config_requires_poll_mode(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("TRIGGER_MODE", raising=False)
    monkeypatch.setenv("GITHUB_POLL_REPOS", "owner/repo")

    with pytest.raises(ValueError, match="TRIGGER_MODE=poll"):
        validate_poller_config()


def test_validate_poller_config_requires_github_repos(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("TRIGGER_MODE", "poll")
    monkeypatch.setenv("ENABLE_GITHUB_POLLER", "true")
    monkeypatch.delenv("GITHUB_POLL_REPOS", raising=False)

    with pytest.raises(ValueError, match="GITHUB_POLL_REPOS"):
        validate_poller_config()


def test_validate_poller_config_accepts_configured_github_repos(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("TRIGGER_MODE", "poll")
    monkeypatch.setenv("ENABLE_GITHUB_POLLER", "true")
    monkeypatch.setenv("ENABLE_LINEAR_POLLER", "false")
    monkeypatch.setenv("GITHUB_POLL_REPOS", "owner/repo")

    assert validate_poller_config() == [("owner", "repo")]


def test_build_issue_comment_payload_uses_comment_author_as_sender() -> None:
    payload = build_issue_comment_payload(
        "owner",
        "repo",
        {"id": 123, "number": 4, "title": "Issue"},
        {
            "id": 456,
            "body": "@openswe please help",
            "created_at": "2026-01-01T00:00:00Z",
            "updated_at": "2026-01-01T00:01:00Z",
            "user": {"login": "octocat", "id": 789},
        },
    )

    assert payload["action"] == "edited"
    assert payload["repository"] == {"owner": {"login": "owner"}, "name": "repo"}
    assert payload["sender"] == {"login": "octocat", "id": 789}
