"""Call the shared utilities defined by architecture.md, without a local fallback."""
from importlib import import_module


def shared(module: str, name: str):
    qualified = f"utils.{module}"
    try:
        imported = import_module(qualified)
    except ModuleNotFoundError as exc:
        if exc.name not in {"utils", qualified}:
            raise
        raise RuntimeError(
            f"SHARED_UTILITIES_UNAVAILABLE: F must provide {qualified}.{name} "
            "as specified in docs/design/architecture.md"
        ) from exc
    return getattr(imported, name)


def artifact_path(name: str, filename: str | None = None) -> str:
    return shared("paths", "artifact_path")(name, filename)


def load_config(filename: str) -> dict:
    return shared("config", "load_config")(filename)


def write_artifact(name: str, obj) -> None:
    shared("io", "write_artifact")(name, obj)
