from .conftest import MAP, SID, bsor, login, login_admin, metadata, reserve, submit


def test_complete_flow_and_moderation(server):
    api, admin, service, upstream, clock, token = server
    login(api)
    status = api.get("/api/v1/qualifiers/status", params={"leagueId": 3023, **MAP})
    assert status.status_code == 200 and status.json()["remainingAttempts"] == 3
    reserved = reserve(api)
    assert reserved.status_code == 201, reserved.text
    result = submit(api, metadata(reserved.json()["challengeId"], "clear"), bsor())
    assert result.status_code == 201, result.text
    submission_id = result.json()["submissionId"]
    api.headers["Authorization"] = "Bearer " + token
    board_path = "/integration/v1/leagues/3023/leaderboard"
    assert api.get(board_path).json()["items"][0]["sid"] == SID
    login_admin(admin)
    detail = admin.get("/admin/api/submissions/" + submission_id)
    assert detail.status_code == 200 and detail.json()["metadata"]["modifiedScore"] == 115
    path = f"/admin/api/submissions/{submission_id}/moderate"
    canceled = admin.post(path, json={"action": "cancel", "version": 0, "reason": "運営確認"})
    assert canceled.status_code == 200, canceled.text
    assert api.get(board_path).json()["items"] == []
    restored = admin.post(path, json={"action": "restore", "version": 1, "reason": "確認済み"})
    assert restored.status_code == 200 and restored.json()["effectiveForRanking"]
    assert len(api.get(board_path).json()["items"]) == 1
    assert [x["event"] for x in api.get("/integration/v1/changes").json()["items"]] == [
        "submitted",
        "canceled",
        "restored",
    ]


def test_metadata_only(server):
    api, _, _, _, _, _ = server
    login(api)
    r = reserve(api)
    assert r.status_code == 201, r.text
    m = metadata(r.json()["challengeId"])
    first = submit(api, m)
    assert first.status_code == 201, first.text
    again = submit(api, m)
    assert again.status_code == 200 and first.content == again.content
