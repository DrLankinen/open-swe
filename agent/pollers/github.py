"""GitHub issue-comment poller for Open SWE."""

from __future__ import annotations

import logging
import os
from datetime import UTC, datetime, timedelta
from typing import Any

import httpx

from agent.utils.github_app import get_github_app_installation_token
from agent.utils.poller_state import get_cursor, mark_processed, set_cursor, was_processed
from agent.webapp import (
    parse_github_issue_comment_trigger,
    parse_github_pr_comment_trigger,
    process_github_issue,
    process_github_pr_comment,
)

logger = logging.getLogger(__name__)

GITHUB_API_BASE = "https://api.github.com"
GITHUB_CURSOR_KEY = "issue_comments_since"
DEDUPE_NAMESPACE = ("poller", "dedupe")
DEFAULT_LOOKBACK_MINUTES = 5


def parse_github_poll_repos(raw_repos: str | None = None) -> list[tuple[str, str]]:
    """Parse GITHUB_POLL_REPOS into (owner, repo) pairs."""
    raw_repos = raw_repos if raw_repos is not None else os.environ.get("GITHUB_POLL_REPOS", "")
    repos: list[tuple[str, str]] = []
    for raw_repo in raw_repos.split(","):
        value = raw_repo.strip()
        if not value:
            continue
        if "/" not in value:
            msg = f"Invalid GitHub poll repo '{value}'. Expected owner/repo."
            raise ValueError(msg)
        owner, repo = value.split("/", 1)
        owner = owner.strip()
        repo = repo.strip()
        if not owner or not repo:
            msg = f"Invalid GitHub poll repo '{value}'. Expected owner/repo."
            raise ValueError(msg)
        repos.append((owner, repo))
    return repos


def _headers(token: str) -> dict[str, str]:
    return {
        "Authorization": f"Bearer {token}",
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
    }


def _repo_namespace(owner: str, repo: str) -> tuple[str, str, str, str]:
    return ("poller", "github", owner, repo)


def _default_since() -> str:
    since = datetime.now(UTC) - timedelta(minutes=DEFAULT_LOOKBACK_MINUTES)
    return since.isoformat().replace("+00:00", "Z")


def _event_id(comment: dict[str, Any]) -> str:
    comment_id = str(comment.get("id", ""))
    updated_at = comment.get("updated_at") or comment.get("created_at") or ""
    return f"github:issue_comment:{comment_id}:{updated_at}"


def _issue_number_from_url(issue_url: str) -> int | None:
    try:
        return int(issue_url.rstrip("/").rsplit("/", 1)[-1])
    except (TypeError, ValueError):
        return None


def _comment_action(comment: dict[str, Any]) -> str:
    created_at = comment.get("created_at")
    updated_at = comment.get("updated_at")
    return "edited" if created_at and updated_at and created_at != updated_at else "created"


async def fetch_issue_comments_since(
    client: httpx.AsyncClient, owner: str, repo: str, since: str
) -> list[dict[str, Any]]:
    """Fetch issue comments updated since the cursor."""
    comments: list[dict[str, Any]] = []
    page = 1
    while True:
        response = await client.get(
            f"{GITHUB_API_BASE}/repos/{owner}/{repo}/issues/comments",
            params={"since": since, "per_page": 100, "page": page},
        )
        response.raise_for_status()
        batch = response.json()
        if not isinstance(batch, list) or not batch:
            break
        comments.extend(batch)
        if len(batch) < 100:
            break
        page += 1
    return comments


async def fetch_issue(
    client: httpx.AsyncClient, owner: str, repo: str, issue_number: int
) -> dict[str, Any] | None:
    """Fetch a GitHub issue for a comment."""
    response = await client.get(f"{GITHUB_API_BASE}/repos/{owner}/{repo}/issues/{issue_number}")
    if response.status_code == 404:
        return None
    response.raise_for_status()
    issue = response.json()
    return issue if isinstance(issue, dict) else None


def build_issue_comment_payload(
    owner: str, repo: str, issue: dict[str, Any], comment: dict[str, Any]
) -> dict[str, Any]:
    """Build the webhook-like payload expected by the existing GitHub processor."""
    comment_user = comment.get("user") or {}
    return {
        "action": _comment_action(comment),
        "issue": issue,
        "comment": comment,
        "repository": {"owner": {"login": owner}, "name": repo},
        "sender": {
            "login": comment_user.get("login", ""),
            "id": comment_user.get("id"),
        },
    }


async def poll_repo(owner: str, repo: str, token: str) -> None:
    """Poll one GitHub repository for issue comments that mention Open SWE."""
    namespace = _repo_namespace(owner, repo)
    since = await get_cursor(namespace, GITHUB_CURSOR_KEY) or _default_since()
    max_seen = since

    async with httpx.AsyncClient(headers=_headers(token), timeout=30) as client:
        comments = await fetch_issue_comments_since(client, owner, repo, since)
        for comment in sorted(comments, key=lambda item: item.get("updated_at") or ""):
            updated_at = comment.get("updated_at") or comment.get("created_at") or ""
            if updated_at and updated_at > max_seen:
                max_seen = updated_at

            event_id = _event_id(comment)
            if await was_processed(DEDUPE_NAMESPACE, event_id):
                continue

            body = (comment.get("body") or "").lower()
            if "@openswe" not in body and "@open-swe" not in body:
                await mark_processed(DEDUPE_NAMESPACE, event_id)
                continue

            issue_number = _issue_number_from_url(comment.get("issue_url", ""))
            if issue_number is None:
                logger.warning("Could not determine issue number for GitHub comment %s", event_id)
                await mark_processed(DEDUPE_NAMESPACE, event_id)
                continue

            issue = await fetch_issue(client, owner, repo, issue_number)
            if not issue:
                await mark_processed(DEDUPE_NAMESPACE, event_id)
                continue
            payload = build_issue_comment_payload(owner, repo, issue, comment)
            if "pull_request" in issue:
                trigger = await parse_github_pr_comment_trigger(payload)
                if trigger.get("status") != "accepted":
                    logger.debug("Ignoring GitHub polled PR comment %s: %s", event_id, trigger)
                    await mark_processed(DEDUPE_NAMESPACE, event_id, trigger)
                    continue
                await process_github_pr_comment(payload, "issue_comment")
                await mark_processed(DEDUPE_NAMESPACE, event_id, {"repo": f"{owner}/{repo}"})
                continue

            trigger = await parse_github_issue_comment_trigger(payload)
            if trigger.get("status") != "accepted":
                logger.debug("Ignoring GitHub polled comment %s: %s", event_id, trigger)
                await mark_processed(DEDUPE_NAMESPACE, event_id, trigger)
                continue

            await process_github_issue(payload, "issue_comment")
            await mark_processed(DEDUPE_NAMESPACE, event_id, {"repo": f"{owner}/{repo}"})

    if max_seen != since:
        await set_cursor(namespace, GITHUB_CURSOR_KEY, max_seen)


async def poll_github_once(repos: list[tuple[str, str]] | None = None) -> None:
    """Poll configured GitHub repositories once."""
    repos = repos if repos is not None else parse_github_poll_repos()
    if not repos:
        logger.info("No GitHub repos configured for polling")
        return

    token = await get_github_app_installation_token()
    if not token:
        logger.error("Cannot poll GitHub: GitHub App installation token is unavailable")
        return

    for owner, repo in repos:
        try:
            await poll_repo(owner, repo, token)
        except Exception:
            logger.exception("GitHub polling failed for %s/%s", owner, repo)
