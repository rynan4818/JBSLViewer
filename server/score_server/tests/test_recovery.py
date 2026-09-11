import sqlite3
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from jbsl_score.api import create_api
from jbsl_score.errors import ApiProblem
from jbsl_score.maintenance import verify_database
from jbsl_score.service import Service

from .conftest import MAP, bsor, login, metadata, reserve, submit


def test_failed_reserve_key_is_bound_across_restart(server):
    api, _, service, upstream, clock, _ = server
    login(api)
    key = str(uuid4())
    upstream.error = ApiProblem(503, "upstream_unavailable", "down")
    assert reserve(api, key).status_code == 503
    upstream.error = None
    restarted = Service(service.config, upstream, service.verifier, clock)
    with TestClient(create_api(restarted, background=False), base_url=service.config.api_public_url) as client:
        client.cookies.update(api.cookies)
        changed = reserve(client, key, map_key={**MAP, "difficulty": "Hard"})
        assert changed.status_code == 409 and changed.json()["error"]["code"] == "idempotency_conflict"
        assert reserve(client, key).status_code == 201
        assert reserve(client, key).status_code == 200


def test_score_replay_feed_and_refund_rollback_together(server, monkeypatch):
    api, _, service, _, _, _ = server
    login(api)
    m = metadata(reserve(api).json()["challengeId"], "clear")

    def interrupted(*args):
        raise sqlite3.OperationalError("simulated disk error after replay insert")

    monkeypatch.setattr(service, "emit_change", interrupted)
    response = submit(api, m, bsor())
    assert response.status_code == 503
    with service.db.read() as c:
        assert c.execute("SELECT COUNT(*) FROM results").fetchone()[0] == 0
        assert c.execute("SELECT COUNT(*) FROM replay_blobs").fetchone()[0] == 0
        assert c.execute("SELECT COUNT(*) FROM changes").fetchone()[0] == 0
        assert c.execute("SELECT status FROM challenges").fetchone()[0] == "reserved"
    monkeypatch.undo()
    assert submit(api, m, bsor()).status_code == 201
    assert verify_database(service.db.path)["replaysChecked"] == 1


def test_version_one_database_upgrade_preserves_receipts(server):
    api, _, service, upstream, clock, _ = server
    login(api)
    key = str(uuid4())
    original = reserve(api, key)
    with service.db.transaction() as c:
        c.execute("DROP TABLE reservation_requests")
        c.execute("DROP TABLE replay_viewer_tokens")
        c.execute("PRAGMA user_version=1")
    upgraded = Service(service.config, upstream, service.verifier, clock)
    with upgraded.db.read() as c:
        assert c.execute("PRAGMA user_version").fetchone()[0] == 3
        assert c.execute("SELECT COUNT(*) FROM reservation_requests").fetchone()[0] == 1
    assert reserve(api, key).content == original.content


@pytest.mark.parametrize(
    "updates",
    [
        {"api_host": "0.0.0.0"},
        {"admin_host": "0.0.0.0"},
        {"trusted_proxy_ips": "*"},
        {"api_public_url": "https://scores.example.test"},
        {"jbsl_web_url": "http://remote.example"},
    ],
)
def test_unsafe_startup_configuration_is_rejected(tmp_path, updates):
    from jbsl_score.config import Config

    with pytest.raises(ValueError):
        Config(data_dir=tmp_path, **updates).validate()
