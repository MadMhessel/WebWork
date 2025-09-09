import sys, pathlib, pytest

sys.path.append(str(pathlib.Path(__file__).resolve().parents[2]))
from WebWork import config


def test_validate_config_missing(monkeypatch):
    monkeypatch.setattr(config, "BOT_TOKEN", "")
    monkeypatch.setattr(config, "CHANNEL_CHAT_ID", "")
    monkeypatch.setattr(config, "CHANNEL_ID", "")
    with pytest.raises(ValueError) as e:
        config.validate_config()
    assert "TELEGRAM_BOT_TOKEN" in str(e.value)


def test_validate_config_ok(monkeypatch):
    monkeypatch.setattr(config, "BOT_TOKEN", "x")
    monkeypatch.setattr(config, "CHANNEL_CHAT_ID", "1")
    monkeypatch.setattr(config, "ENABLE_MODERATION", False)
    config.validate_config()
