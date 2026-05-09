"""Durable cursor and dedupe helpers for polling-based triggers."""

from __future__ import annotations

import os
from datetime import UTC, datetime
from typing import Any

from langgraph_sdk import get_client

LANGGRAPH_URL = os.environ.get("LANGGRAPH_URL") or os.environ.get(
    "LANGGRAPH_URL_PROD", "http://localhost:2024"
)
STATUS_NAMESPACE = ("poller", "status")


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


async def get_status(key: str) -> dict[str, Any] | None:
    """Read a poller status record from the LangGraph store."""
    item = await _client().store.get_item(STATUS_NAMESPACE, key)
    if not item:
        return None
    value = item.get("value")
    return value if isinstance(value, dict) else None


async def get_statuses(keys: list[str]) -> dict[str, dict[str, Any] | None]:
    """Read multiple poller status records."""
    statuses: dict[str, dict[str, Any] | None] = {}
    for key in keys:
        statuses[key] = await get_status(key)
    return statuses


async def put_status(key: str, value: dict[str, Any]) -> None:
    """Persist a poller status record."""
    payload = dict(value)
    payload["updated_at"] = _now_iso()
    await _client().store.put_item(STATUS_NAMESPACE, key, payload)


async def update_status(key: str, updates: dict[str, Any]) -> dict[str, Any]:
    """Merge updates into a poller status record and persist it."""
    current = await get_status(key) or {}
    merged = {**current, **updates}
    await put_status(key, merged)
    return merged


async def safe_update_status(key: str, updates: dict[str, Any]) -> None:
    """Best-effort status update that must not break polling."""
    try:
        await update_status(key, updates)
    except Exception:  # noqa: BLE001
        return
