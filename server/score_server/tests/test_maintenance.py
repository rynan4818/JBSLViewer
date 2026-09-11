from dataclasses import asdict

import pytest

from jbsl_score.config import Config
from jbsl_score.maintenance import backup, restore_backup, verify_database
from jbsl_score.service import Service

from .conftest import bsor, login, login_admin, metadata, reserve, submit


def test_online_backup_and_restore_all_data(server, tmp_path):
    api, admin, service, upstream, clock, token = server
    login(api)
    login_admin(admin)
    m = metadata(reserve(api).json()["challengeId"], "clear")
    result = submit(api, m, bsor())
    assert result.status_code == 201
    name = backup(service)["file"]
    source = service.config.data_dir / "backups" / name
    report = verify_database(source)
    assert report == {"integrity": "ok", "replaysChecked": 1, "challenges": 1, "results": 1}
    destination = tmp_path / "restored"
    assert restore_backup(source, destination) == report
    restored = Service(Config(data_dir=destination), upstream, service.verifier, clock)
    assert verify_database(restored.db.path) == report
    with restored.db.read() as c:
        assert c.execute("SELECT response_json FROM results").fetchone()[0] == result.text
        assert c.execute("SELECT COUNT(*) FROM sessions").fetchone()[0] == 0
        assert c.execute("SELECT COUNT(*) FROM admin_sessions").fetchone()[0] == 0
        assert c.execute("SELECT COUNT(*) FROM service_tokens WHERE revoked_at IS NULL").fetchone()[0] == 0
    with pytest.raises(ValueError):
        restore_backup(source, destination)


def test_retention_removes_only_generated_backups(server):
    _, _, service, _, clock, _ = server
    policy, revision = service.db.policy()
    service.update_policy({**asdict(policy), "backup_keep_count": 2}, revision, "test", "test")
    directory = service.config.data_dir / "backups"
    directory.mkdir()
    unrelated = directory / "important.sqlite3"
    unrelated.write_text("keep")
    for _ in range(3):
        backup(service)
        clock.now += 1
    assert len(list(directory.glob("score-*.sqlite3"))) == 2
    assert unrelated.read_text() == "keep"


def test_verifier_detects_replay_and_budget_corruption(server):
    api, _, service, _, _, _ = server
    login(api)
    m = metadata(reserve(api).json()["challengeId"], "clear")
    assert submit(api, m, bsor()).status_code == 201
    with service.db.transaction() as c:
        c.execute("UPDATE replay_blobs SET raw_size=raw_size+1")
    with pytest.raises(ValueError, match="Replay digest"):
        verify_database(service.db.path)
    with service.db.transaction() as c:
        c.execute("UPDATE replay_blobs SET raw_size=raw_size-1")
        c.execute("UPDATE budgets SET used=0")
    with pytest.raises(ValueError, match="accounting"):
        verify_database(service.db.path)


def test_moderation_conflict_and_unranked_restore_stay_unranked(server):
    api, admin, service, _, _, _ = server
    login(api)
    login_admin(admin)
    m = metadata(reserve(api).json()["challengeId"])
    submitted = submit(api, m)
    result_id = submitted.json()["submissionId"]
    path = f"/admin/api/submissions/{result_id}/moderate"
    assert admin.post(path, json={"action": "cancel", "version": 0, "reason": "取消"}).status_code == 200
    assert admin.post(path, json={"action": "restore", "version": 0, "reason": "古い画面"}).status_code == 409
    response = admin.post(path, json={"action": "restore", "version": 1, "reason": "復元"})
    assert response.status_code == 200 and response.json()["effectiveForRanking"] is False
    assert submit(api, m).content == submitted.content
    assert verify_database(service.db.path)["results"] == 1


def test_feed_pagination_and_historical_payload(server):
    api, admin, service, _, _, token = server
    login(api)
    login_admin(admin)
    result = submit(api, metadata(reserve(api).json()["challengeId"], "clear"), bsor()).json()
    path = f"/admin/api/submissions/{result['submissionId']}/moderate"
    admin.post(path, json={"action": "cancel", "version": 0, "reason": "cancel"})
    admin.post(path, json={"action": "restore", "version": 1, "reason": "restore"})
    api.headers["Authorization"] = "Bearer " + token
    cursor, events = 0, []
    for _ in range(4):
        r = api.get("/integration/v1/changes", params={"after": cursor, "limit": 1}).json()
        events += r["items"]
        cursor = r["nextCursor"]
        if not r["hasMore"]:
            break
    assert [x["event"] for x in events] == ["submitted", "canceled", "restored"]
    assert [x["submission"]["canceled"] for x in events] == [False, True, False]
    assert api.get("/integration/v1/changes", params={"after": cursor}).json()["items"] == []
