"""Durable cursor and dedupe helpers for polling-based triggers."""

from __future__ import annotations

import os
from datetime import UTC, datetime
from typing import Any

from langgraph_sdk import get_client

LANGGRAPH_URL = os.environ.get("LANGGRAPH_URL") or os.environ.get(
    "LANGGRAPH_URL_PROD", "http://localhost:2024"
)


def _client():
    return get_client(url=LANGGRAPH_URL)


def _now_iso() -> str:
    return datetime.now(UTC).isoformat().replace("+00:00", "Z")


async def get_cursor(namespace: tuple[str, ...], key: str) -> str | None:
    """Read a cursor value from the LangGraph store."""
    item = await _client().store.get_item(namespace, key)
    if not item:
        return None
    value = item.get("value") or {}
    cursor = value.get("cursor")
    return cursor if isinstance(cursor, str) and cursor else None


async def set_cursor(namespace: tuple[str, ...], key: str, value: str) -> None:
    """Persist a cursor value in the LangGraph store."""
    await _client().store.put_item(
        namespace,
        key,
        {"cursor": value, "updated_at": _now_iso()},
    )


async def was_processed(namespace: tuple[str, ...], event_id: str) -> bool:
    """Return whether a polled event has already been processed."""
    item = await _client().store.get_item(namespace, event_id)
    return bool(item)


async def mark_processed(
    namespace: tuple[str, ...], event_id: str, payload: dict[str, Any] | None = None
) -> None:
    """Mark a polled event as processed."""
    await _client().store.put_item(
        namespace,
        event_id,
        {"processed_at": _now_iso(), "payload": payload or {}},
    )
