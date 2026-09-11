from fastapi.testclient import TestClient

from mock_servers.score_manager.config import Settings
from mock_servers.score_manager.score_manager_server import create_app
from .conftest import authenticate, fixture_projections, FakeLeaderboardClient


def test_cookie_session_round_trip_and_delete(server):
    client, *_ = server
    auth = authenticate(client)
    assert "HttpOnly" in auth.headers["set-cookie"] and "SameSite=lax" in auth.headers["set-cookie"]
    assert "Secure" not in auth.headers["set-cookie"]
    assert client.get("/api/v1/auth/me").json()["user"]["sid"] == "76561198000000000"
    assert client.delete("/api/v1/auth/session").status_code == 204
    assert client.get("/api/v1/auth/me").status_code == 401


def test_invalid_ticket_and_provider_are_rejected(server):
    client, *_ = server
    assert client.post("/api/v1/auth/session", data={"ticket": "", "provider": "steamTicket", "returnUrl": "/"}).status_code == 401
    assert client.post("/api/v1/auth/session", data={"ticket": "x", "provider": "other", "returnUrl": "/"}).status_code == 400


def test_rate_limit_returns_retry_after(tmp_path):
    settings = Settings(database_path=tmp_path / "db.sqlite3", replay_dir=tmp_path / "replays", rate_limit_enabled=True, allow_insecure_loopback_cookie=True)
    with TestClient(create_app(settings, FakeLeaderboardClient(fixture_projections()))) as client:
        for _ in range(5): assert client.post("/api/v1/auth/session", data={"ticket": "x", "provider": "steamTicket", "returnUrl": "/"}).status_code == 200
        limited = client.post("/api/v1/auth/session", data={"ticket": "x", "provider": "steamTicket", "returnUrl": "/"})
        assert limited.status_code == 429 and limited.headers["retry-after"] == "60"


def test_http_requires_explicit_development_setting(tmp_path):
    settings = Settings(database_path=tmp_path / "db.sqlite3", replay_dir=tmp_path / "replays", rate_limit_enabled=False, allow_insecure_loopback_cookie=False)
    with TestClient(create_app(settings, FakeLeaderboardClient(fixture_projections()))) as client:
        response = client.post("/api/v1/auth/session", data={"ticket": "x", "provider": "steamTicket", "returnUrl": "/"})
        assert response.status_code == 403


def test_https_cookie_is_secure_without_development_exception(tmp_path):
    settings = Settings(database_path=tmp_path / "db.sqlite3", replay_dir=tmp_path / "replays", rate_limit_enabled=False, allow_insecure_loopback_cookie=False)
    with TestClient(create_app(settings, FakeLeaderboardClient(fixture_projections())), base_url="https://testserver") as client:
        response = client.post("/api/v1/auth/session", data={"ticket": "x", "provider": "steamTicket", "returnUrl": "/"})
        assert response.status_code == 200 and "Secure" in response.headers["set-cookie"]
        assert client.get("/api/v1/auth/me").status_code == 200
