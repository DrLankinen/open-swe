import os
from pathlib import Path

from deepagents.backends import LocalShellBackend

DEFAULT_LOCAL_SANDBOX_WORKSPACES_DIR = ".workspaces"


def create_local_sandbox(sandbox_id: str | None = None):
    """Create a local shell sandbox with no isolation.

    WARNING: This runs commands directly on the host machine with no sandboxing.
    Only use for local development with human-in-the-loop enabled.

    The root directory defaults to a clearly marked .workspaces directory under
    the current working directory and can be overridden via the
    LOCAL_SANDBOX_ROOT_DIR environment variable.

    Args:
        sandbox_id: Ignored for local sandboxes; accepted for interface compatibility.

    Returns:
        LocalShellBackend instance implementing SandboxBackendProtocol.
    """
    root_dir = os.getenv("LOCAL_SANDBOX_ROOT_DIR")
    if not root_dir:
        root_dir = str(Path(os.getcwd()) / DEFAULT_LOCAL_SANDBOX_WORKSPACES_DIR)
    Path(root_dir).mkdir(parents=True, exist_ok=True)

    return LocalShellBackend(
        root_dir=root_dir,
        inherit_env=True,
    )
