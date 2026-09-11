import multiprocessing
from concurrent.futures import ThreadPoolExecutor
from uuid import uuid4

from jbsl_score.config import Config
from jbsl_score.maintenance import verify_database
from jbsl_score.service import Service

from .conftest import Clock, MAP, SID, Upstream, Verifier, login, metadata, reserve, submit


def test_100_same_key_http_requests(server):
    api, _, service, upstream, _, _ = server
    login(api)
    upstream.data["maps"][0]["qualifier_attempt_limit"] = 1
    key = str(uuid4())
    with ThreadPoolExecutor(max_workers=100) as pool:
        responses = list(pool.map(lambda _: reserve(api, key), range(100)))
    assert [r.status_code for r in responses].count(201) == 1
    assert [r.status_code for r in responses].count(200) == 99
    assert len({r.content for r in responses}) == 1
    assert upstream.calls == 1
    assert verify_database(service.db.path)["challenges"] == 1


def test_100_distinct_keys_cannot_overdraw_last_attempt(server):
    api, _, service, upstream, _, _ = server
    login(api)
    upstream.data["maps"][0]["qualifier_attempt_limit"] = 1
    with ThreadPoolExecutor(max_workers=50) as pool:
        responses = list(pool.map(lambda _: reserve(api), range(100)))
    assert [r.status_code for r in responses].count(201) == 1
    assert [r.status_code for r in responses].count(409) == 99
    assert verify_database(service.db.path)["challenges"] == 1


def process_reservations(data_dir, key, event, queue):
    try:
        service = Service(Config(data_dir=data_dir), Upstream(), Verifier(), Clock())
        event.wait(20)
        responses = []
        for _ in range(25):
            responses.append(
                service.reserve(
                    {"sid": SID, "provider": "steamTicket"},
                    key,
                    {
                        "schemaVersion": 1,
                        "leagueId": 3023,
                        "map": MAP,
                        "clientVersion": "process-test",
                        "gameVersion": "1.29.1",
                    },
                    "test",
                )
            )
        queue.put(responses)
    except BaseException as exc:
        queue.put({"error": repr(exc)})


def test_100_reserves_across_four_processes(server):
    api, _, service, _, _, _ = server
    login(api)
    context = multiprocessing.get_context("spawn")
    queue, event, key = context.Queue(), context.Event(), str(uuid4())
    workers = [
        context.Process(target=process_reservations, args=(service.config.data_dir, key, event, queue))
        for _ in range(4)
    ]
    try:
        for worker in workers:
            worker.start()
        event.set()
        groups = [queue.get(timeout=60) for _ in workers]
        assert all(isinstance(g, list) for g in groups), groups
        responses = [r for group in groups for r in group]
        assert [r[0] for r in responses].count(201) == 1
        assert [r[0] for r in responses].count(200) == 99
        assert len({r[1] for r in responses}) == 1
        assert verify_database(service.db.path)["challenges"] == 1
    finally:
        for worker in workers:
            worker.join(timeout=15)
            if worker.is_alive():
                worker.terminate()
                worker.join()
        queue.close()


def test_duplicate_results_refund_once_under_concurrency(server):
    api, _, service, _, _, _ = server
    from .test_rules import policy

    policy(service, refund_conditions=["preflight_unstarted"])
    login(api)
    m = metadata(reserve(api).json()["challengeId"])
    with ThreadPoolExecutor(max_workers=100) as pool:
        responses = list(pool.map(lambda _: submit(api, m), range(100)))
    assert [r.status_code for r in responses].count(201) == 1
    assert [r.status_code for r in responses].count(200) == 99
    assert len({r.content for r in responses}) == 1
    assert responses[0].json()["remainingAttempts"] == 3
    assert verify_database(service.db.path)["results"] == 1
