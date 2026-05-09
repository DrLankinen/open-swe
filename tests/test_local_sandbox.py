from __future__ import annotations

from agent.integrations.local import create_local_sandbox


def test_create_local_sandbox_defaults_to_workspaces_dir(tmp_path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("LOCAL_SANDBOX_ROOT_DIR", raising=False)

    sandbox = create_local_sandbox()

    result = sandbox.execute("pwd")
    assert result.exit_code == 0
    assert result.output.strip() == str(tmp_path / ".workspaces")
    assert (tmp_path / ".workspaces").is_dir()


def test_create_local_sandbox_respects_root_dir_override(tmp_path, monkeypatch) -> None:
    root_dir = tmp_path / "custom-workspace"
    monkeypatch.setenv("LOCAL_SANDBOX_ROOT_DIR", str(root_dir))

    sandbox = create_local_sandbox()

    result = sandbox.execute("pwd")
    assert result.exit_code == 0
    assert result.output.strip() == str(root_dir)
    assert root_dir.is_dir()
