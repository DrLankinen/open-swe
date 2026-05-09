import os
from importlib import import_module

SANDBOX_FACTORIES: dict[str, tuple[str, str]] = {
    "langsmith": ("agent.integrations.langsmith", "create_langsmith_sandbox"),
    "daytona": ("agent.integrations.daytona", "create_daytona_sandbox"),
    "modal": ("agent.integrations.modal", "create_modal_sandbox"),
    "runloop": ("agent.integrations.runloop", "create_runloop_sandbox"),
    "local": ("agent.integrations.local", "create_local_sandbox"),
}


def create_sandbox(sandbox_id: str | None = None):
    """Create or reconnect to a sandbox using the configured provider.

    The provider is selected via the SANDBOX_TYPE environment variable.
    Supported values: langsmith (default), daytona, modal, runloop, local.

    Args:
        sandbox_id: Optional existing sandbox ID to reconnect to.

    Returns:
        A sandbox backend implementing SandboxBackendProtocol.
    """
    sandbox_type = os.getenv("SANDBOX_TYPE", "langsmith").strip().lower()
    factory_ref = SANDBOX_FACTORIES.get(sandbox_type)
    if not factory_ref:
        supported = ", ".join(sorted(SANDBOX_FACTORIES))
        raise ValueError(f"Invalid sandbox type: {sandbox_type}. Supported types: {supported}")
    module_name, factory_name = factory_ref
    factory = getattr(import_module(module_name), factory_name)
    return factory(sandbox_id)


def validate_sandbox_startup_config() -> None:
    """Validate the configured sandbox provider's env vars at server startup.

    Raises ValueError if the active provider's configuration is invalid.
    Called from the FastAPI lifespan hook so errors surface at boot rather
    than on the first sandbox creation.
    """
    sandbox_type = os.getenv("SANDBOX_TYPE", "langsmith").strip().lower()
    if sandbox_type == "langsmith":
        from agent.integrations.langsmith import LangSmithProvider

        LangSmithProvider.validate_startup_config()
