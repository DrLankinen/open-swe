from __future__ import annotations

from typing import Any

import pytest

from agent.prompt import construct_system_prompt
from agent.utils import linear


@pytest.mark.asyncio
async def test_update_issue_resolves_state_name(monkeypatch: pytest.MonkeyPatch) -> None:
    requests: list[tuple[str, dict[str, Any] | None]] = []

    async def fake_graphql_request(
        query: str, variables: dict[str, Any] | None = None
    ) -> dict[str, Any]:
        requests.append((query, variables))
        if "GetIssueTeamStates" in query:
            return {
                "issue": {
                    "team": {
                        "states": {
                            "nodes": [
                                {"id": "todo-state", "name": "Todo"},
                                {"id": "review-state", "name": "In Review"},
                            ]
                        }
                    }
                }
            }
        return {"issueUpdate": {"success": True, "issue": {"id": "issue-id"}}}

    monkeypatch.setattr(linear, "_graphql_request", fake_graphql_request)

    result = await linear.update_issue("issue-id", state_name="in review")

    assert result == {"success": True, "issue": {"id": "issue-id"}}
    assert requests[1][1] == {"id": "issue-id", "input": {"stateId": "review-state"}}


@pytest.mark.asyncio
async def test_update_issue_returns_error_when_state_name_is_missing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def fake_graphql_request(
        query: str, variables: dict[str, Any] | None = None
    ) -> dict[str, Any]:
        return {"issue": {"team": {"states": {"nodes": [{"id": "todo", "name": "Todo"}]}}}}

    monkeypatch.setattr(linear, "_graphql_request", fake_graphql_request)

    result = await linear.update_issue("issue-id", state_name="In Review")

    assert result == {"error": "State 'In Review' not found for issue issue-id"}


def test_prompt_opens_normal_pr_and_updates_linear_status() -> None:
    rendered = construct_system_prompt(working_dir="/workspace")

    assert "gh pr create --draft" not in rendered
    assert "Open PRs in normal mode; do not pass `--draft`" in rendered
    assert 'state_name="In Review"' in rendered
