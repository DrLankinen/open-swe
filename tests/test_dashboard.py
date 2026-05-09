from __future__ import annotations

from fastapi.testclient import TestClient

from agent import webapp
from agent.pollers import github as github_poller
from agent.pollers import linear as linear_poller


def test_dashboard_serves_local_admin_page() -> None:
    client = TestClient(webapp.app)

    response = client.get("/dashboard")

    assert response.status_code == 200
    assert "Open SWE" in response.text
    assert "/api/dashboard/status" in response.text


def test_dashboard_rejects_non_local_requests() -> None:
    client = TestClient(webapp.app, client=("10.0.0.4", 1234))

    response = client.get("/dashboard")

    assert response.status_code == 403


def test_dashboard_status_uses_configured_repos(
    monkeypatch,
) -> None:
    monkeypatch.setenv("ENABLE_GITHUB_POLLER", "true")
    monkeypatch.setenv("ENABLE_LINEAR_POLLER", "false")
    monkeypatch.setenv("GITHUB_POLL_REPOS", "owner/repo")

    async def fake_get_statuses(keys: list[str]) -> dict[str, dict | None]:
        assert keys == ["github", "linear", "github:owner/repo"]
        return {
            "github": {"running": False, "last_finished_at": "2026-01-01T00:00:00Z"},
            "linear": {"running": False},
            "github:owner/repo": {"last_cursor": {"issue_comments": "cursor"}},
        }

    monkeypatch.setattr("agent.utils.poller_state.get_statuses", fake_get_statuses)
    client = TestClient(webapp.app)

    response = client.get("/api/dashboard/status")

    assert response.status_code == 200
    payload = response.json()
    assert payload["pollers"]["github"]["configured_repos"] == ["owner/repo"]
    assert payload["pollers"]["github"]["repos"][0]["last_cursor"] == {"issue_comments": "cursor"}
    assert payload["pollers"]["linear"]["enabled"] is False


def test_dashboard_trigger_github_calls_poller(monkeypatch) -> None:
    monkeypatch.setenv("ENABLE_GITHUB_POLLER", "true")
    monkeypatch.setenv("GITHUB_POLL_REPOS", "owner/repo")
    called: dict[str, object] = {}

    async def fake_poll_github_once(repos: list[tuple[str, str]]) -> dict[str, object]:
        called["repos"] = repos
        return {"status": "success", "poller": "github"}

    monkeypatch.setattr(github_poller, "poll_github_once", fake_poll_github_once)
    client = TestClient(webapp.app)

    response = client.post("/api/dashboard/trigger/github")

    assert response.status_code == 200
    assert response.json() == {"status": "success", "poller": "github"}
    assert called["repos"] == [("owner", "repo")]


def test_dashboard_trigger_linear_calls_poller(monkeypatch) -> None:
    monkeypatch.setenv("ENABLE_LINEAR_POLLER", "true")
    called: dict[str, bool] = {}

    async def fake_poll_linear_once() -> dict[str, object]:
        called["linear"] = True
        return {"status": "success", "poller": "linear"}

    monkeypatch.setattr(linear_poller, "poll_linear_once", fake_poll_linear_once)
    client = TestClient(webapp.app)

    response = client.post("/api/dashboard/trigger/linear")

    assert response.status_code == 200
    assert response.json() == {"status": "success", "poller": "linear"}
    assert called["linear"] is True
