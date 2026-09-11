import json

import pytest

from mock_servers.jbsl_web_proxy import config
from mock_servers.jbsl_web_proxy.control import Control


@pytest.mark.parametrize("value,expected", [
    ("", ""), ("  ", ""),
    ("https://jbsl-qualifier.rynan.com", "https://jbsl-qualifier.rynan.com"),
    (" HTTPS://JBSL-QUALIFIER.RYNAN.COM:443/ ", "https://jbsl-qualifier.rynan.com"),
])
def test_public_url_normalization(value, expected):
    assert config.normalize_public_url(value) == expected


@pytest.mark.parametrize("value", [
    None, False, 443, [], {}, "http://relay.example", "//relay.example",
    "https://127.0.0.1", "https://127.1", "https://0x7f.0x1", "https://[::1]", "https://localhost",
    "https://relay.example:18080", "https://relay.example:", "https://relay.example:bad",
    "https://relay.example/admin/", "https://relay.example?", "https://relay.example#",
    "https://user:password@relay.example", "https://relay.example\\admin",
    "https://relay.\nexample", "https://relay..example", "https://-relay.example",
])
def test_invalid_public_url_is_rejected(value):
    with pytest.raises(ValueError, match="public_url"):
        config.normalize_public_url(value)


def test_config_is_resolved_from_server_folder_and_supports_windows_bom(tmp_path, monkeypatch):
    folder = tmp_path / "server"
    folder.mkdir()
    monkeypatch.setattr(config, "ROOT", folder)
    monkeypatch.chdir(tmp_path)
    assert config.load_public_url() == ""
    (folder / "config.json").write_text('{"public_url":"https://relay.example/"}', encoding="utf-8-sig")
    (tmp_path / "config.json").write_text('{"public_url":"https://wrong.example"}', encoding="utf-8")
    assert config.load_public_url() == "https://relay.example"
    assert config.Settings.from_env().public_url == "https://relay.example"


@pytest.mark.parametrize("data", [{}, {"public_url": ""}])
def test_empty_config_keeps_local_operation(tmp_path, data):
    path = tmp_path / "config.json"
    path.write_text(json.dumps(data), encoding="utf-8")
    control = Control(tmp_path / "data", public_url=config.load_public_url(path))
    assert control.browser_urls == control.urls


@pytest.mark.parametrize("text", ['{invalid', '[]', 'null', '{"publicUrl":"https://relay.example"}', '{"public_url":42}'])
def test_bad_config_fails_instead_of_falling_back_to_local(tmp_path, text):
    path = tmp_path / "config.json"
    path.write_text(text, encoding="utf-8")
    with pytest.raises(ValueError, match="config.json"):
        config.load_public_url(path)


def test_distribution_uses_empty_config_template():
    manifest = json.loads((config.ROOT / "package-files.json").read_text(encoding="utf-8"))
    entry, = [item for item in manifest["files"] if item["target"] == "config.json"]
    assert entry["source"] != "config.json"
    assert config.load_public_url(config.ROOT / entry["source"]) == ""
