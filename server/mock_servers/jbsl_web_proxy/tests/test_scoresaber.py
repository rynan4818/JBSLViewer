import asyncio
import copy
import json
import threading
import time
from concurrent.futures import ThreadPoolExecutor

import httpx
import pytest
from fastapi.testclient import TestClient

from mock_servers.jbsl_web_proxy.config import Settings
from mock_servers.jbsl_web_proxy.control import TrafficLog
from mock_servers.jbsl_web_proxy.jbsl_web_proxy_server import create_app
from mock_servers.jbsl_web_proxy.scoresaber import ScoreSaber


SID = "76561198245534518"
OTHER = "0009007199254740993"


def test_total_rank_priority_and_map_only_names_use_scoresaber():
    calls = []
    def handle(request):
        calls.append(str(request.url))
        assert "authorization" not in request.headers and "cookie" not in request.headers
        return httpx.Response(200, json={"id": OTHER, "name": "ScoreSaber 日本語"})
    client = ScoreSaber(transport=httpx.MockTransport(handle))
    board = {"participants": [{"sid": SID}, {"sid": OTHER}],
             "total_rank": [None, {"sid": SID, "name": " JBSL Name "}, {"sid": SID, "name": "Duplicate"}],
             "maps": [{"scores": [{"sid": OTHER, "name": "Map name is not the source"}]}]}
    rankings = copy.deepcopy(board["total_rank"])
    asyncio.run(client.fill(board))
    assert board["participants"] == [{"sid": SID, "name": "JBSL Name"}, {"sid": OTHER, "name": "ScoreSaber 日本語"}]
    assert board["total_rank"] == rankings
    assert calls == ["https://scoresaber.com/api/v2/players/" + OTHER]
    asyncio.run(client.fill(board))
    assert len(calls) == 1


@pytest.mark.parametrize("failure", [404, 429, 503, "timeout", "json", "size", "id", "numeric_id", "name"])
def test_lookup_failures_keep_stale_name_and_retry_after_cooldown(failure):
    now, calls = [100.0], []
    def handle(request):
        calls.append(request)
        if len(calls) != 2:
            return httpx.Response(200, json={"id": SID, "name": "Cached" if len(calls) == 1 else "Updated"})
        if isinstance(failure, int):
            return httpx.Response(failure)
        if failure == "timeout":
            raise httpx.ReadTimeout("offline")
        if failure == "json":
            return httpx.Response(200, content=b"{invalid")
        if failure == "size":
            return httpx.Response(200, content=b" " * (2 * 1024 * 1024 + 1))
        return httpx.Response(200, json={"id": OTHER if failure == "id" else int(SID) if failure == "numeric_id" else SID,
                                        "name": None if failure == "name" else "Wrong"})
    log = TrafficLog()
    client = ScoreSaber(log, httpx.MockTransport(handle), clock=lambda: now[0])
    assert asyncio.run(client.name(SID)) == "Cached"
    now[0] += 3601
    assert asyncio.run(client.name(SID)) == "Cached"
    assert asyncio.run(client.name(SID)) == "Cached"
    assert len(calls) == 2 and log.read()[-1]["errorCode"]
    now[0] += 61
    assert asyncio.run(client.name(SID)) == "Updated"
    assert len(calls) == 3


@pytest.mark.parametrize("name", [None, 1, {}, [], "", "  ", "x" * 201, "a\x00b", "a\ud800b", SID])
def test_invalid_optional_names_fall_back_to_exact_sid(name):
    calls = []
    def handle(request):
        calls.append(request)
        return httpx.Response(200, content=json.dumps({"id": SID, "name": name}).encode())
    client = ScoreSaber(transport=httpx.MockTransport(handle))
    board = {"participants": [{"sid": SID}], "total_rank": [{"sid": SID, "name": name}]}
    assert asyncio.run(client.fill(board))["participants"] == [{"sid": SID, "name": SID}]
    assert asyncio.run(client.fill(board))["participants"] == [{"sid": SID, "name": SID}]
    assert len(calls) == 1


def test_total_rank_name_can_be_used_when_lookup_later_fails():
    client = ScoreSaber(transport=httpx.MockTransport(lambda _: httpx.Response(404)))
    board = {"participants": [{"sid": SID}], "total_rank": [{"sid": SID, "name": "Last ranking name"}]}
    asyncio.run(client.fill(board))
    board["total_rank"] = []
    assert asyncio.run(client.fill(board))["participants"] == [{"sid": SID, "name": "Last ranking name"}]


def test_same_sid_is_shared_across_admin_and_proxy_event_loops():
    calls, lock, start = [], threading.Lock(), threading.Barrier(2)
    async def handle(request):
        with lock:
            calls.append(request)
        await asyncio.sleep(0.05)
        return httpx.Response(200, json={"id": SID, "name": "Shared"})
    client = ScoreSaber(transport=httpx.MockTransport(handle))
    def request():
        start.wait(timeout=5)
        return asyncio.run(client.name(SID))
    with ThreadPoolExecutor(max_workers=2) as pool:
        futures = [pool.submit(request) for _ in range(2)]
        assert [f.result(timeout=5) for f in futures] == ["Shared", "Shared"]
    assert len(calls) == 1


def test_concurrency_is_bounded_and_same_sid_requests_are_coalesced():
    active, maximum, calls = 0, 0, []
    async def handle(request):
        nonlocal active, maximum
        active += 1
        maximum = max(maximum, active)
        calls.append(request)
        try:
            await asyncio.sleep(0.01)
            sid = request.url.path.rsplit("/", 1)[-1]
            return httpx.Response(200, json={"id": sid, "name": "Name " + sid})
        finally:
            active -= 1
    client = ScoreSaber(transport=httpx.MockTransport(handle))
    board = {"participants": [{"sid": str(i)} for i in range(8)]}
    async def run():
        return await asyncio.gather(*(client.fill(copy.deepcopy(board)) for _ in range(3)))
    results = asyncio.run(run())
    assert results[0] == results[1] == results[2]
    assert all(p["name"] == "Name " + p["sid"] for p in results[0]["participants"])
    assert len(calls) == 8 and 1 < maximum <= 4 and active == 0


def test_batch_timeout_returns_participants_and_releases_pending_requests():
    active = 0
    async def handle(request):
        nonlocal active
        active += 1
        try:
            await asyncio.sleep(5)
            return httpx.Response(404)
        finally:
            active -= 1
    client = ScoreSaber(transport=httpx.MockTransport(handle), fill_timeout=0.05)
    board = {"participants": [{"sid": str(i)} for i in range(8)]}
    started = time.monotonic()
    result = asyncio.run(client.fill(board))
    assert time.monotonic() - started < 1
    assert result["participants"] == [{"sid": str(i), "name": str(i)} for i in range(8)]
    assert active == 0 and not client._pending


@pytest.mark.parametrize("live", [False, True])
def test_standalone_proxy_enriches_participants_with_transport_injection(tmp_path, monkeypatch, live):
    settings = Settings()
    fixture = json.loads(settings.fixture_path.read_text(encoding="utf-8"))
    fixture["leagues"]["3023"]["participants"].append({"sid": SID})
    settings.fixture_path = tmp_path / "fixture.json"
    settings.fixture_path.write_text(json.dumps(fixture), encoding="utf-8")
    if live:
        board = json.loads((settings.offline_upstream_dir / "leaderboard_3023.json").read_text(encoding="utf-8"))
        client_class = httpx.AsyncClient
        monkeypatch.setattr(httpx, "AsyncClient", lambda **kwargs: client_class(
            **{**kwargs, "transport": kwargs.get("transport") or httpx.MockTransport(lambda _: httpx.Response(200, json=board))}))
        settings.offline_upstream_dir = None
    app = create_app(settings)
    app.state.scoresaber = ScoreSaber(transport=httpx.MockTransport(
        lambda _: httpx.Response(200, json={"id": SID, "name": "リュナン"})))
    with TestClient(app) as api:
        response = api.get("/leaderboard/api/3023")
        assert response.status_code == 200
        assert {"sid": SID, "name": "リュナン"} in response.json()["participants"]
