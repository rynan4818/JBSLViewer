from datetime import timedelta

from mock_servers.score_manager.errors import ApiProblem
from .conftest import MAP_A, authenticate


def status(client, league=3023, map_key=MAP_A):
    return client.get("/api/v1/qualifiers/status", params={"leagueId": league, **map_key, "jbslRevision": "42"})


def test_status_cache_nullability_and_reason_priority(server):
    client, _, _, upstream, _ = server; authenticate(client)
    first = status(client); second = status(client)
    assert first.status_code == 200 and first.json()["reasonCode"] == "eligible"
    assert second.status_code == 200 and upstream.calls == 1
    missing = status(client, 9999).json()
    assert missing["reasonCode"] == "league_not_found"
    assert missing["league"] is None and missing["map"] is None and missing["remainingAttempts"] is None
    nonq = status(client, 3024, {"hash": "A" * 40, "characteristic": "Standard", "difficulty": "Hard"}).json()
    assert nonq["reasonCode"] == "qualifier_disabled" and nonq["eligible"] is False
    closed = status(client, 3025, {"hash": "B" * 40, "characteristic": "Standard", "difficulty": "ExpertPlus"}).json()
    assert closed["reasonCode"] == "league_not_open" and closed["remainingAttempts"] == 1


def test_stale_is_display_only_and_reserve_never_uses_it(server):
    client, _, _, upstream, clock = server; authenticate(client)
    assert status(client).status_code == 200
    clock.value += timedelta(seconds=61); upstream.error = ApiProblem(503, "upstream_unavailable", "offline")
    stale = status(client)
    assert stale.status_code == 200 and stale.json()["cache"]["stale"] is True and stale.json()["reasonCode"] == "upstream_unavailable"
    from .conftest import reserve
    failed = reserve(client)
    assert failed.status_code == 503
    assert client.get("/__mock__/state").json()["budgets"] == []

