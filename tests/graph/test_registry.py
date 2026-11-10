from types import SimpleNamespace

import pytest

from graph import registry


def test_registry_uses_mock_switches_and_real_by_default(monkeypatch):
    monkeypatch.setattr(registry, "load_config", lambda filename: {"probe_input": True})
    imported = []

    def module(name):
        imported.append(name)
        return SimpleNamespace(**{name.split(".")[-1]: lambda state: {}})

    monkeypatch.setattr(registry, "import_module", module)
    assert set(registry.resolve_nodes()) == set(registry.NODE_NAMES)
    assert imported[0] == "mocks.probe_input"
    assert all(name.startswith("nodes.") for name in imported[1:])


@pytest.mark.parametrize("flags", [{"typo": True}, {"asr_diarize": "false"}])
def test_invalid_switches_fail_before_import(monkeypatch, flags):
    monkeypatch.setattr(registry, "load_config", lambda filename: flags)
    with pytest.raises((ValueError, TypeError)):
        registry.resolve_nodes()
