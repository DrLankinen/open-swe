from __future__ import annotations

import pytest

from agent import webapp
from agent.poller_main import validate_poller_config
from agent.pollers import github as github_poller
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


async def test_parse_github_pr_comment_trigger_accepts_pr_conversation_comment() -> None:
    payload = build_issue_comment_payload(
        "owner",
        "repo",
        {"id": 123, "number": 4, "title": "PR", "pull_request": {}},
        {"id": 456, "body": "@openswe please help", "user": {"login": "octocat"}},
    )

    assert await webapp.parse_github_pr_comment_trigger(payload) == {"status": "accepted"}


async def test_parse_github_pr_comment_trigger_rejects_issue_comment() -> None:
    payload = build_issue_comment_payload(
        "owner",
        "repo",
        {"id": 123, "number": 4, "title": "Issue"},
        {"id": 456, "body": "@openswe please help", "user": {"login": "octocat"}},
    )

    result = await webapp.parse_github_pr_comment_trigger(payload)

    assert result["status"] == "ignored"


async def test_poll_repo_routes_pr_conversation_comments(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    called: dict[str, object] = {}

    async def fake_get_cursor(namespace: tuple[str, ...], key: str) -> str:
        return "2026-01-01T00:00:00Z"

    async def fake_set_cursor(namespace: tuple[str, ...], key: str, value: str) -> None:
        called["cursor"] = value

    async def fake_was_processed(namespace: tuple[str, ...], event_id: str) -> bool:
        return False

    async def fake_mark_processed(
        namespace: tuple[str, ...], event_id: str, payload: dict | None = None
    ) -> None:
        called["processed"] = event_id

    async def fake_fetch_issue_comments_since(*args: object) -> list[dict[str, object]]:
        return [
            {
                "id": 456,
                "body": "@openswe please help",
                "created_at": "2026-01-01T00:01:00Z",
                "updated_at": "2026-01-01T00:01:00Z",
                "issue_url": "https://api.github.com/repos/owner/repo/issues/4",
                "user": {"login": "octocat", "id": 789},
            }
        ]

    async def fake_fetch_issue(*args: object) -> dict[str, object]:
        return {
            "id": 123,
            "number": 4,
            "title": "PR",
            "html_url": "https://github.com/owner/repo/pull/4",
            "pull_request": {},
        }

    async def fake_process_github_pr_comment(payload: dict, event_type: str) -> None:
        called["payload"] = payload
        called["event_type"] = event_type

    async def fake_process_github_issue(payload: dict, event_type: str) -> None:
        raise AssertionError("issue processor should not handle PR comments")

    monkeypatch.setattr(github_poller, "get_cursor", fake_get_cursor)
    monkeypatch.setattr(github_poller, "set_cursor", fake_set_cursor)
    monkeypatch.setattr(github_poller, "was_processed", fake_was_processed)
    monkeypatch.setattr(github_poller, "mark_processed", fake_mark_processed)
    monkeypatch.setattr(github_poller, "fetch_issue_comments_since", fake_fetch_issue_comments_since)
    monkeypatch.setattr(github_poller, "fetch_issue", fake_fetch_issue)
    monkeypatch.setattr(github_poller, "process_github_pr_comment", fake_process_github_pr_comment)
    monkeypatch.setattr(github_poller, "process_github_issue", fake_process_github_issue)

    await github_poller.poll_repo("owner", "repo", "token")

    assert called["event_type"] == "issue_comment"
    assert called["payload"]["issue"]["pull_request"] == {}
