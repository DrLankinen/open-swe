"""Polling-only trigger runner for Open SWE."""

from __future__ import annotations

import asyncio
import logging
import os
from datetime import UTC, datetime, timedelta

from agent.pollers.github import parse_github_poll_repos, poll_github_once
from agent.pollers.linear import poll_linear_once
from agent.utils.poller_state import safe_update_status

logger = logging.getLogger(__name__)


def _env_bool(name: str, default: bool = False) -> bool:
    value = os.environ.get(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


def _poll_interval_seconds() -> float:
    raw_value = os.environ.get("POLL_INTERVAL_SECONDS", "30")
    try:
        interval = float(raw_value)
    except ValueError as exc:
        msg = f"POLL_INTERVAL_SECONDS must be a number, got {raw_value!r}"
        raise ValueError(msg) from exc
    if interval <= 0:
        msg = "POLL_INTERVAL_SECONDS must be greater than 0"
        raise ValueError(msg)
    return interval


def _now_iso() -> str:
    return datetime.now(UTC).isoformat().replace("+00:00", "Z")


def _next_run_iso(interval: float) -> str:
    return (datetime.now(UTC) + timedelta(seconds=interval)).isoformat().replace("+00:00", "Z")


def validate_poller_config() -> list[tuple[str, str]]:
    """Validate polling-only configuration and return configured GitHub repos."""
    trigger_mode = os.environ.get("TRIGGER_MODE", "").strip().lower()
    if trigger_mode != "poll":
        msg = "Set TRIGGER_MODE=poll to run polling triggers."
        raise ValueError(msg)

    github_enabled = _env_bool("ENABLE_GITHUB_POLLER", default=True)
    linear_enabled = _env_bool("ENABLE_LINEAR_POLLER", default=True)
    if not github_enabled and not linear_enabled:
        msg = "At least one poller must be enabled."
        raise ValueError(msg)

    repos: list[tuple[str, str]] = []
    if github_enabled:
        repos = parse_github_poll_repos()
        if not repos:
            msg = "Set GITHUB_POLL_REPOS=owner/repo[,owner/repo] when ENABLE_GITHUB_POLLER=true."
            raise ValueError(msg)

    _poll_interval_seconds()
    return repos


async def run_pollers_forever() -> None:
    """Run enabled pollers until the process is stopped."""
    logging.basicConfig(level=os.environ.get("LOG_LEVEL", "INFO"))
    repos = validate_poller_config()
    github_enabled = _env_bool("ENABLE_GITHUB_POLLER", default=True)
    linear_enabled = _env_bool("ENABLE_LINEAR_POLLER", default=True)
    interval = _poll_interval_seconds()

    logger.info(
        "Starting Open SWE pollers: github=%s linear=%s interval=%ss",
        github_enabled,
        linear_enabled,
        interval,
    )

    while True:
        next_run_at = _next_run_iso(interval)
        if github_enabled:
            await poll_github_once(repos)
            await safe_update_status(
                "github",
                {
                    "enabled": True,
                    "poll_interval_seconds": interval,
                    "next_run_at": next_run_at,
                    "configured_repos": [f"{owner}/{repo}" for owner, repo in repos],
                },
            )
            for owner, repo in repos:
                await safe_update_status(
                    f"github:{owner}/{repo}",
                    {
                        "enabled": True,
                        "poll_interval_seconds": interval,
                        "next_run_at": next_run_at,
                        "repo": f"{owner}/{repo}",
                    },
                )
        if linear_enabled:
            try:
                await poll_linear_once()
            except Exception:
                logger.exception("Linear polling failed")
                await safe_update_status(
                    "linear",
                    {
                        "running": False,
                        "last_finished_at": _now_iso(),
                        "last_error": "Linear polling failed",
                    },
                )
            await safe_update_status(
                "linear",
                {
                    "enabled": True,
                    "poll_interval_seconds": interval,
                    "next_run_at": next_run_at,
                },
            )
        if not github_enabled:
            await safe_update_status("github", {"enabled": False, "running": False})
        if not linear_enabled:
            await safe_update_status("linear", {"enabled": False, "running": False})
        await asyncio.sleep(interval)


def main() -> None:
    asyncio.run(run_pollers_forever())


if __name__ == "__main__":
    main()
