"""Linear comment poller for Open SWE."""

from __future__ import annotations

import logging
import os
from datetime import UTC, datetime, timedelta
from typing import Any

import httpx

from agent.utils.poller_state import (
    get_cursor,
    mark_processed,
    safe_update_status,
    set_cursor,
    was_processed,
)
from agent.webapp import parse_linear_comment_trigger, process_linear_issue

logger = logging.getLogger(__name__)

LINEAR_API_URL = "https://api.linear.app/graphql"
LINEAR_CURSOR_NAMESPACE = ("poller", "linear")
LINEAR_CURSOR_KEY = "comments_since"
DEDUPE_NAMESPACE = ("poller", "dedupe")
DEFAULT_LOOKBACK_MINUTES = 5


def _default_since() -> str:
    since = datetime.now(UTC) - timedelta(minutes=DEFAULT_LOOKBACK_MINUTES)
    return since.isoformat().replace("+00:00", "Z")


def _now_iso() -> str:
    return datetime.now(UTC).isoformat().replace("+00:00", "Z")


def _event_id(comment: dict[str, Any]) -> str:
    comment_id = str(comment.get("id", ""))
    updated_at = comment.get("updatedAt") or comment.get("createdAt") or ""
    return f"linear:comment:{comment_id}:{updated_at}"


def _headers(api_key: str) -> dict[str, str]:
    return {"Authorization": api_key, "Content-Type": "application/json"}


async def fetch_recent_linear_comments(
    client: httpx.AsyncClient, since: str
) -> list[dict[str, Any]]:
    """Fetch Linear comments updated since the cursor."""
    query = """
    query PollComments($since: DateTimeOrDuration!, $after: String) {
        comments(
            first: 100,
            after: $after,
            filter: { updatedAt: { gte: $since } }
        ) {
            nodes {
                id
                body
                createdAt
                updatedAt
                user {
                    id
                    name
                    email
                }
                issue {
                    id
                    identifier
                    title
                    url
                    team {
                        id
                        name
                        key
                    }
                    project {
                        id
                        name
                    }
                }
            }
            pageInfo {
                hasNextPage
                endCursor
            }
        }
    }
    """

    comments: list[dict[str, Any]] = []
    after: str | None = None
    while True:
        response = await client.post(
            LINEAR_API_URL,
            json={"query": query, "variables": {"since": since, "after": after}},
        )
        response.raise_for_status()
        result = response.json()
        if result.get("errors"):
            msg = f"Linear comments query failed: {result['errors']}"
            raise RuntimeError(msg)
        data = result.get("data", {}).get("comments", {})
        nodes = data.get("nodes") or []
        comments.extend(node for node in nodes if isinstance(node, dict))
        page_info = data.get("pageInfo") or {}
        if not page_info.get("hasNextPage"):
            break
        after = page_info.get("endCursor")
        if not after:
            break
    return comments


def build_linear_comment_payload(comment: dict[str, Any]) -> dict[str, Any]:
    """Build the event payload expected by the shared Linear parser."""
    return {
        "type": "Comment",
        "action": "create",
        "data": {
            "id": comment.get("id", ""),
            "body": comment.get("body", ""),
            "user": comment.get("user") or {},
            "issue": comment.get("issue") or {},
            "botActor": False,
        },
    }


async def poll_linear_once() -> dict[str, Any]:
    """Poll Linear once for comments that mention Open SWE."""
    started_at = _now_iso()
    await safe_update_status(
        "linear",
        {"enabled": True, "running": True, "last_started_at": started_at, "last_error": None},
    )
    summary: dict[str, Any] = {
        "poller": "linear",
        "started_at": started_at,
        "comments_scanned": 0,
        "accepted_triggers": 0,
        "ignored_events": 0,
        "errors": [],
    }
    api_key = os.environ.get("LINEAR_API_KEY", "")
    if not api_key:
        logger.info("Cannot poll Linear: LINEAR_API_KEY is not configured")
        finished_at = _now_iso()
        summary.update(
            {
                "finished_at": finished_at,
                "status": "skipped",
                "reason": "LINEAR_API_KEY is not configured",
            }
        )
        await safe_update_status(
            "linear",
            {
                "running": False,
                "last_finished_at": finished_at,
                "last_error": "LINEAR_API_KEY is not configured",
                "summary": summary,
            },
        )
        return summary

    since = await get_cursor(LINEAR_CURSOR_NAMESPACE, LINEAR_CURSOR_KEY) or _default_since()
    max_seen = since
    summary["cursor"] = since

    try:
        async with httpx.AsyncClient(headers=_headers(api_key), timeout=30) as client:
            comments = await fetch_recent_linear_comments(client, since)
    except Exception as exc:
        logger.exception("Linear polling failed")
        finished_at = _now_iso()
        error = str(exc) or type(exc).__name__
        summary.update({"finished_at": finished_at, "status": "error"})
        summary["errors"].append(error)
        await safe_update_status(
            "linear",
            {
                "running": False,
                "last_finished_at": finished_at,
                "last_error": error,
                "summary": summary,
            },
        )
        return summary

    summary["comments_scanned"] = len(comments)

    for comment in sorted(comments, key=lambda item: item.get("updatedAt") or ""):
        updated_at = comment.get("updatedAt") or comment.get("createdAt") or ""
        if updated_at and updated_at > max_seen:
            max_seen = updated_at

        event_id = _event_id(comment)
        if await was_processed(DEDUPE_NAMESPACE, event_id):
            summary["ignored_events"] += 1
            continue

        body = (comment.get("body") or "").lower()
        if "@openswe" not in body:
            summary["ignored_events"] += 1
            await mark_processed(DEDUPE_NAMESPACE, event_id)
            continue

        payload = build_linear_comment_payload(comment)
        trigger = await parse_linear_comment_trigger(payload)
        if trigger.get("status") != "accepted":
            logger.debug("Ignoring Linear polled comment %s: %s", event_id, trigger)
            summary["ignored_events"] += 1
            await mark_processed(DEDUPE_NAMESPACE, event_id, trigger)
            continue

        summary["accepted_triggers"] += 1
        await process_linear_issue(trigger["issue"], trigger["repo_config"])
        await mark_processed(DEDUPE_NAMESPACE, event_id, {"issue": comment.get("issue", {})})

    if max_seen != since:
        await set_cursor(LINEAR_CURSOR_NAMESPACE, LINEAR_CURSOR_KEY, max_seen)
    finished_at = _now_iso()
    summary.update({"finished_at": finished_at, "status": "success", "cursor": max_seen})
    await safe_update_status(
        "linear",
        {
            "running": False,
            "last_finished_at": finished_at,
            "last_success_at": finished_at,
            "last_error": None,
            "last_cursor": max_seen,
            "summary": summary,
        },
    )
    return summary
