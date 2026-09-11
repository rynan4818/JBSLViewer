"""URLs and scoped access for external BSOR viewers."""

import re
import secrets
from urllib.parse import quote, urlencode

from .contracts import require_uuid
from .database import token_hash
from .errors import ApiProblem
from .replay import decompress_gzip
from .service import timestamp

REPLAY_PATH = "/api/v1/replay-viewer/{submission_id}/{player_id}.bsor"
REPLAY_PATH_PATTERN = re.compile(r"/api/v1/replay-viewer/[0-9a-fA-F-]{36}/[0-9]{1,32}\.bsor")
PUBLIC_REPLAY_PATH = "/api/v1/public/replays/{submission_id}/{player_id}.bsor"
PUBLIC_REPLAY_PATH_PATTERN = re.compile(r"/api/v1/public/replays/[0-9a-fA-F-]{36}/[0-9]{1,32}\.bsor")
PUBLIC_DOWNLOAD_PATH = "/admin/api/public/submissions/{submission_id}/replay"
VIEWERS = {
    "beatleader": ("https://replay.beatleader.com", "/", "link"),
    "arcviewer": ("https://allpoland.github.io", "/ArcViewer/", "replayURL"),
}
VIEWER_ORIGINS = frozenset(item[0] for item in VIEWERS.values())
TOKEN_SECONDS = 600


def available(service):
    return service.config.api_public_url.startswith("https://")


def viewer_url(viewer, replay_url):
    origin, path, parameter = VIEWERS[viewer]
    params = {parameter: replay_url}
    if viewer == "arcviewer":
        params["noProxy"] = "true"
    return origin + path + "?" + urlencode(params)


def public_links(service, submission_id, player_id, has_replay):
    links = {"downloadUrl": None, "beatleaderUrl": None, "arcviewerUrl": None}
    if has_replay:
        links["downloadUrl"] = PUBLIC_DOWNLOAD_PATH.format(submission_id=submission_id)
        if available(service):
            replay_url = service.config.api_public_url.rstrip("/") + PUBLIC_REPLAY_PATH.format(
                submission_id=submission_id, player_id=quote(player_id, safe=""),
            )
            for viewer in VIEWERS:
                links[viewer + "Url"] = viewer_url(viewer, replay_url)
    return links


def issue(service, admin, submission_id, body, request_id):
    submission_id = require_uuid(submission_id, "submissionId")
    if (
        not isinstance(body, dict) or set(body) != {"viewer"}
        or not isinstance(body["viewer"], str) or body["viewer"] not in VIEWERS
    ):
        raise ApiProblem(400, "malformed_request", "viewerにはbeatleaderまたはarcviewerを指定してください。")
    if not available(service):
        raise ApiProblem(409, "replay_viewer_unavailable", "外部再生にはAPI公開URLのHTTPS設定が必要です。")
    now, token = service.clock(), secrets.token_urlsafe(32)
    service.db.rate_limit("replay_viewer_issue", admin["username"], 30, now)
    with service.db.transaction() as c:
        session = c.execute(
            "SELECT expires_at FROM admin_sessions WHERE token_hash=? AND expires_at>?",
            (admin["token_hash"], now),
        ).fetchone()
        if session is None:
            raise ApiProblem(401, "admin_login_required", "管理者ログインが必要です。")
        row = c.execute(
            "SELECT ch.sid,r.challenge_id FROM replay_blobs b JOIN results r ON r.id=b.result_id "
            "JOIN challenges ch ON ch.id=r.challenge_id WHERE r.id=?", (submission_id,),
        ).fetchone()
        if row is None:
            raise ApiProblem(404, "replay_not_found", "Replay does not exist.")
        expires = min(now + TOKEN_SECONDS, session["expires_at"])
        c.execute(
            "INSERT INTO replay_viewer_tokens VALUES(?,?,?,?,?,?)",
            (token_hash(token), submission_id, admin["token_hash"], body["viewer"], now, expires),
        )
        service.db.audit(
            now, "admin:" + admin["username"], "replay_viewer_issued", row["challenge_id"], request_id,
            {"submissionId": submission_id, "viewer": body["viewer"], "expiresAt": timestamp(expires)}, connection=c,
        )
    replay_url = service.config.api_public_url.rstrip("/") + REPLAY_PATH.format(
        submission_id=submission_id, player_id=quote(row["sid"], safe=""),
    ) + "?" + urlencode({"token": token})
    return {"viewerUrl": viewer_url(body["viewer"], replay_url), "expiresAt": timestamp(expires)}


def authorize(service, submission_id, player_id, token, origin):
    submission_id = require_uuid(submission_id, "submissionId")
    if not isinstance(token, str) or not re.fullmatch(r"[A-Za-z0-9_-]{43}", token):
        raise ApiProblem(401, "replay_viewer_token_invalid", "再生URLが無効です。提出結果から再度開いてください。")
    now = service.clock()
    with service.db.read() as c:
        row = c.execute(
            "SELECT t.viewer,ch.sid,a.username FROM replay_viewer_tokens t "
            "JOIN admin_sessions a ON a.token_hash=t.admin_session_hash "
            "JOIN results r ON r.id=t.result_id JOIN challenges ch ON ch.id=r.challenge_id "
            "WHERE t.token_hash=? AND t.result_id=? AND t.expires_at>? AND a.expires_at>?",
            (token_hash(token), submission_id, now, now),
        ).fetchone()
    if row is None or row["sid"] != player_id:
        raise ApiProblem(401, "replay_viewer_token_invalid", "再生URLが無効または期限切れです。提出結果から再度開いてください。")
    if origin is not None and origin != VIEWERS[row["viewer"]][0]:
        raise ApiProblem(403, "replay_viewer_origin_rejected", "This replay URL belongs to another viewer.")
    return dict(row)


def read_replay(service, submission_id, token):
    service.db.rate_limit("replay_viewer_read", token, 30, service.clock())
    with service.db.read() as c:
        row = c.execute("SELECT gzip_data FROM replay_blobs WHERE result_id=?", (submission_id,)).fetchone()
    if row is None:
        raise ApiProblem(404, "replay_not_found", "Replay does not exist.")
    return decompress_gzip(row[0], service.config.compressed_replay_limit, service.config.expanded_replay_limit)
