"""GitHub issue-comment poller for Open SWE."""

from __future__ import annotations

import logging
import os
from datetime import UTC, datetime, timedelta
from typing import Any

import httpx

from agent.utils.github_app import get_github_app_installation_token
from agent.utils.poller_state import (
    get_cursor,
    mark_processed,
    safe_update_status,
    set_cursor,
    was_processed,
)
from agent.webapp import (
    parse_github_issue_comment_trigger,
    parse_github_pr_comment_trigger,
    parse_github_pr_review_comment_trigger,
    process_github_issue,
    process_github_pr_comment,
)

logger = logging.getLogger(__name__)

GITHUB_API_BASE = "https://api.github.com"
ISSUE_COMMENTS_CURSOR_KEY = "issue_comments_since"
PR_REVIEW_COMMENTS_CURSOR_KEY = "pr_review_comments_since"
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


def _repo_status_key(owner: str, repo: str) -> str:
    return f"github:{owner}/{repo}"


def _default_since() -> str:
    since = datetime.now(UTC) - timedelta(minutes=DEFAULT_LOOKBACK_MINUTES)
    return since.isoformat().replace("+00:00", "Z")


def _now_iso() -> str:
    return datetime.now(UTC).isoformat().replace("+00:00", "Z")


def _issue_comment_event_id(comment: dict[str, Any]) -> str:
    comment_id = str(comment.get("id", ""))
    updated_at = comment.get("updated_at") or comment.get("created_at") or ""
    return f"github:issue_comment:{comment_id}:{updated_at}"


def _pr_review_comment_event_id(comment: dict[str, Any]) -> str:
    comment_id = str(comment.get("id", ""))
    updated_at = comment.get("updated_at") or comment.get("created_at") or ""
    return f"github:pr_review_comment:{comment_id}:{updated_at}"


def _issue_number_from_url(issue_url: str) -> int | None:
    try:
        return int(issue_url.rstrip("/").rsplit("/", 1)[-1])
    except (TypeError, ValueError):
        return None


def _pr_number_from_url(pull_request_url: str) -> int | None:
    try:
        return int(pull_request_url.rstrip("/").rsplit("/", 1)[-1])
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


async def fetch_pr_review_comments_since(
    client: httpx.AsyncClient, owner: str, repo: str, since: str
) -> list[dict[str, Any]]:
    """Fetch inline PR review comments updated since the cursor."""
    comments: list[dict[str, Any]] = []
    page = 1
    while True:
        response = await client.get(
            f"{GITHUB_API_BASE}/repos/{owner}/{repo}/pulls/comments",
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


async def fetch_pull_request(
    client: httpx.AsyncClient, owner: str, repo: str, pr_number: int
) -> dict[str, Any] | None:
    """Fetch a GitHub pull request for an inline review comment."""
    response = await client.get(f"{GITHUB_API_BASE}/repos/{owner}/{repo}/pulls/{pr_number}")
    if response.status_code == 404:
        return None
    response.raise_for_status()
    pull_request = response.json()
    return pull_request if isinstance(pull_request, dict) else None


def build_issue_comment_payload(
    owner: str, repo: str, issue: dict[str, Any], comment: dict[str, Any]
) -> dict[str, Any]:
    """Build the event payload expected by the existing GitHub processor."""
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


def build_pr_review_comment_payload(
    owner: str, repo: str, pull_request: dict[str, Any], comment: dict[str, Any]
) -> dict[str, Any]:
    """Build the event payload expected by the existing PR comment processor."""
    comment_user = comment.get("user") or {}
    return {
        "action": _comment_action(comment),
        "pull_request": pull_request,
        "comment": comment,
        "repository": {"owner": {"login": owner}, "name": repo},
        "sender": {
            "login": comment_user.get("login", ""),
            "id": comment_user.get("id"),
        },
    }


async def poll_repo(owner: str, repo: str, token: str) -> dict[str, Any]:
    """Poll one GitHub repository for issue comments that mention Open SWE."""
    namespace = _repo_namespace(owner, repo)
    issue_since = await get_cursor(namespace, ISSUE_COMMENTS_CURSOR_KEY) or _default_since()
    issue_max_seen = issue_since
    review_since = await get_cursor(namespace, PR_REVIEW_COMMENTS_CURSOR_KEY) or _default_since()
    review_max_seen = review_since
    summary: dict[str, Any] = {
        "repo": f"{owner}/{repo}",
        "issue_comments_scanned": 0,
        "review_comments_scanned": 0,
        "accepted_triggers": 0,
        "ignored_events": 0,
        "issue_cursor": issue_since,
        "review_cursor": review_since,
    }

    async with httpx.AsyncClient(headers=_headers(token), timeout=30) as client:
        comments = await fetch_issue_comments_since(client, owner, repo, issue_since)
        summary["issue_comments_scanned"] = len(comments)
        for comment in sorted(comments, key=lambda item: item.get("updated_at") or ""):
            updated_at = comment.get("updated_at") or comment.get("created_at") or ""
            if updated_at and updated_at > issue_max_seen:
                issue_max_seen = updated_at

            event_id = _issue_comment_event_id(comment)
            if await was_processed(DEDUPE_NAMESPACE, event_id):
                summary["ignored_events"] += 1
                continue

            body = (comment.get("body") or "").lower()
            if "@openswe" not in body and "@open-swe" not in body:
                summary["ignored_events"] += 1
                await mark_processed(DEDUPE_NAMESPACE, event_id)
                continue

            issue_number = _issue_number_from_url(comment.get("issue_url", ""))
            if issue_number is None:
                logger.warning("Could not determine issue number for GitHub comment %s", event_id)
                summary["ignored_events"] += 1
                await mark_processed(DEDUPE_NAMESPACE, event_id)
                continue

            issue = await fetch_issue(client, owner, repo, issue_number)
            if not issue:
                summary["ignored_events"] += 1
                await mark_processed(DEDUPE_NAMESPACE, event_id)
                continue
            payload = build_issue_comment_payload(owner, repo, issue, comment)
            if "pull_request" in issue:
                trigger = await parse_github_pr_comment_trigger(payload)
                if trigger.get("status") != "accepted":
                    logger.debug("Ignoring GitHub polled PR comment %s: %s", event_id, trigger)
                    summary["ignored_events"] += 1
                    await mark_processed(DEDUPE_NAMESPACE, event_id, trigger)
                    continue
                summary["accepted_triggers"] += 1
                await process_github_pr_comment(payload, "issue_comment")
                await mark_processed(DEDUPE_NAMESPACE, event_id, {"repo": f"{owner}/{repo}"})
                continue

            trigger = await parse_github_issue_comment_trigger(payload)
            if trigger.get("status") != "accepted":
                logger.debug("Ignoring GitHub polled comment %s: %s", event_id, trigger)
                summary["ignored_events"] += 1
                await mark_processed(DEDUPE_NAMESPACE, event_id, trigger)
                continue

            summary["accepted_triggers"] += 1
            await process_github_issue(payload, "issue_comment")
            await mark_processed(DEDUPE_NAMESPACE, event_id, {"repo": f"{owner}/{repo}"})

        review_comments = await fetch_pr_review_comments_since(client, owner, repo, review_since)
        summary["review_comments_scanned"] = len(review_comments)
        for comment in sorted(review_comments, key=lambda item: item.get("updated_at") or ""):
            updated_at = comment.get("updated_at") or comment.get("created_at") or ""
            if updated_at and updated_at > review_max_seen:
                review_max_seen = updated_at

            event_id = _pr_review_comment_event_id(comment)
            if await was_processed(DEDUPE_NAMESPACE, event_id):
                summary["ignored_events"] += 1
                continue

            body = (comment.get("body") or "").lower()
            if "@openswe" not in body and "@open-swe" not in body:
                summary["ignored_events"] += 1
                await mark_processed(DEDUPE_NAMESPACE, event_id)
                continue

            pr_number = _pr_number_from_url(comment.get("pull_request_url", ""))
            if pr_number is None:
                logger.warning(
                    "Could not determine PR number for GitHub review comment %s", event_id
                )
                summary["ignored_events"] += 1
                await mark_processed(DEDUPE_NAMESPACE, event_id)
                continue

            pull_request = await fetch_pull_request(client, owner, repo, pr_number)
            if not pull_request:
                summary["ignored_events"] += 1
                await mark_processed(DEDUPE_NAMESPACE, event_id)
                continue

            payload = build_pr_review_comment_payload(owner, repo, pull_request, comment)
            trigger = await parse_github_pr_review_comment_trigger(payload)
            if trigger.get("status") != "accepted":
                logger.debug("Ignoring GitHub polled review comment %s: %s", event_id, trigger)
                summary["ignored_events"] += 1
                await mark_processed(DEDUPE_NAMESPACE, event_id, trigger)
                continue

            summary["accepted_triggers"] += 1
            await process_github_pr_comment(payload, "pull_request_review_comment")
            await mark_processed(DEDUPE_NAMESPACE, event_id, {"repo": f"{owner}/{repo}"})

    if issue_max_seen != issue_since:
        await set_cursor(namespace, ISSUE_COMMENTS_CURSOR_KEY, issue_max_seen)
    if review_max_seen != review_since:
        await set_cursor(namespace, PR_REVIEW_COMMENTS_CURSOR_KEY, review_max_seen)
    summary["issue_cursor"] = issue_max_seen
    summary["review_cursor"] = review_max_seen
    return summary


async def poll_github_once(repos: list[tuple[str, str]] | None = None) -> dict[str, Any]:
    """Poll configured GitHub repositories once."""
    repos = repos if repos is not None else parse_github_poll_repos()
    started_at = _now_iso()
    repo_names = [f"{owner}/{repo}" for owner, repo in repos]
    await safe_update_status(
        "github",
        {
            "enabled": True,
            "running": True,
            "configured_repos": repo_names,
            "last_started_at": started_at,
            "last_error": None,
        },
    )
    summary: dict[str, Any] = {
        "poller": "github",
        "started_at": started_at,
        "repos": [],
        "accepted_triggers": 0,
        "errors": [],
    }
    if not repos:
        logger.info("No GitHub repos configured for polling")
        finished_at = _now_iso()
        summary.update({"finished_at": finished_at, "status": "skipped", "reason": "no repos"})
        await safe_update_status(
            "github",
            {
                "running": False,
                "last_finished_at": finished_at,
                "last_error": "No repos configured",
            },
        )
        return summary

    token = await get_github_app_installation_token()
    if not token:
        logger.error("Cannot poll GitHub: GitHub App installation token is unavailable")
        finished_at = _now_iso()
        summary.update({"finished_at": finished_at, "status": "error"})
        summary["errors"].append("GitHub App installation token is unavailable")
        await safe_update_status(
            "github",
            {
                "running": False,
                "last_finished_at": finished_at,
                "last_error": "GitHub App installation token is unavailable",
            },
        )
        return summary

    for owner, repo in repos:
        repo_started_at = _now_iso()
        await safe_update_status(
            _repo_status_key(owner, repo),
            {
                "enabled": True,
                "running": True,
                "repo": f"{owner}/{repo}",
                "last_started_at": repo_started_at,
                "last_error": None,
            },
        )
        try:
            repo_summary = await poll_repo(owner, repo, token)
            repo_finished_at = _now_iso()
            summary["repos"].append(repo_summary)
            summary["accepted_triggers"] += repo_summary["accepted_triggers"]
            await safe_update_status(
                _repo_status_key(owner, repo),
                {
                    "running": False,
                    "last_finished_at": repo_finished_at,
                    "last_success_at": repo_finished_at,
                    "last_error": None,
                    "summary": repo_summary,
                    "last_cursor": {
                        "issue_comments": repo_summary["issue_cursor"],
                        "review_comments": repo_summary["review_cursor"],
                    },
                },
            )
        except Exception as exc:
            logger.exception("GitHub polling failed for %s/%s", owner, repo)
            repo_finished_at = _now_iso()
            error = str(exc) or type(exc).__name__
            summary["errors"].append({"repo": f"{owner}/{repo}", "error": error})
            await safe_update_status(
                _repo_status_key(owner, repo),
                {"running": False, "last_finished_at": repo_finished_at, "last_error": error},
            )
    finished_at = _now_iso()
    status = "error" if summary["errors"] else "success"
    summary.update({"finished_at": finished_at, "status": status})
    await safe_update_status(
        "github",
        {
            "running": False,
            "last_finished_at": finished_at,
            "last_success_at": finished_at if status == "success" else None,
            "last_error": summary["errors"][-1] if summary["errors"] else None,
            "summary": summary,
        },
    )
    return summary
