import pytest

from atlas.inference import keys

CANARY = "apikey_" + "0" * 36 + "_" + "f" * 64


def test_env_var_wins_and_keychain_is_not_called(monkeypatch):
    monkeypatch.setenv("TYPESAFE_API_KEY", CANARY)
    monkeypatch.setattr(keys, "_keychain", lambda: pytest.fail("keychain read"))
    assert keys.get_api_key() == CANARY


def test_missing_key_error_does_not_leak(monkeypatch):
    monkeypatch.delenv("TYPESAFE_API_KEY", raising=False)
    monkeypatch.setattr(keys, "_keychain", lambda: None)
    with pytest.raises(keys.MissingKey) as exc:
        keys.get_api_key()
    assert "Keychain" in str(exc.value)


def test_base_url_default_and_override(monkeypatch):
    monkeypatch.delenv("TYPESAFE_BASE_URL", raising=False)
    assert keys.base_url() == "https://api.typesafe.ai"
    monkeypatch.setenv("TYPESAFE_BASE_URL", "http://127.0.0.1:9")
    assert keys.base_url() == "http://127.0.0.1:9"
