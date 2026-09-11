from __future__ import annotations

import asyncio
import hashlib
import logging
import os
import sqlite3
import time
from contextlib import asynccontextmanager
from uuid import uuid4

from fastapi.concurrency import run_in_threadpool

from .errors import ApiProblem
from .locks import FileLock
from .replay import decompress_gzip
from .service import timestamp
from .timing import measure_operation

LOG = logging.getLogger("jbsl_score")


def verify_database(path, *, full=True):
    c = sqlite3.connect(f"{path.resolve().as_uri()}?mode=ro", uri=True)
    try:
        integrity = [row[0] for row in c.execute("PRAGMA integrity_check")]
        if integrity != ["ok"] or c.execute("PRAGMA foreign_key_check").fetchall():
            raise ValueError("Database integrity check failed")
        mismatches = c.execute(
            "SELECT COUNT(*) FROM budgets b WHERE b.used<>(SELECT COUNT(*) FROM challenges c "
            "WHERE c.sid=b.sid AND c.league_id=b.league_id AND c.map_hash=b.map_hash AND c.characteristic=b.characteristic "
            "AND c.difficulty=b.difficulty AND c.refunded=0) OR b.total<>(SELECT COUNT(*) FROM challenges c "
            "WHERE c.sid=b.sid AND c.league_id=b.league_id AND c.map_hash=b.map_hash AND c.characteristic=b.characteristic AND c.difficulty=b.difficulty)"
        ).fetchone()[0]
        if mismatches:
            raise ValueError("Attempt accounting is inconsistent")
        if c.execute(
            "SELECT COUNT(*) FROM results r LEFT JOIN replay_blobs b ON b.result_id=r.id "
            "WHERE (r.replay_sha256 IS NULL)<>(b.result_id IS NULL)"
        ).fetchone()[0]:
            raise ValueError("Replay references are inconsistent")
        checked = 0
        if full:
            for blob, size, sha in c.execute(
                "SELECT b.gzip_data,b.raw_size,r.replay_sha256 FROM replay_blobs b JOIN results r ON r.id=b.result_id"
            ):
                raw = decompress_gzip(blob, 16 * 1024 * 1024, 64 * 1024 * 1024)
                if len(raw) != size or hashlib.sha256(raw).hexdigest() != sha:
                    raise ValueError("Replay digest check failed")
                checked += 1
        return {
            "integrity": "ok",
            "replaysChecked": checked,
            "challenges": c.execute("SELECT COUNT(*) FROM challenges").fetchone()[0],
            "results": c.execute("SELECT COUNT(*) FROM results").fetchone()[0],
        }
    finally:
        c.close()


@measure_operation()
def backup(service, actor="system"):
    with FileLock(service.lock_dir, "backup"):
        policy, _ = service.db.policy()
        service.check_disk(policy)
        directory = service.config.data_dir / "backups"
        directory.mkdir(parents=True, exist_ok=True)
        name = time.strftime("score-%Y%m%d-%H%M%S", time.gmtime(service.clock())) + "-" + uuid4().hex[:8] + ".sqlite3"
        destination = directory / name
        pending = destination.with_suffix(".pending")
        try:
            target = sqlite3.connect(pending)
            try:
                with service.db.read() as source:
                    source.backup(target, pages=256, sleep=0.01)
            finally:
                target.close()
            report = verify_database(pending, full=True)
            with pending.open("r+b") as stream:
                os.fsync(stream.fileno())
            pending.replace(destination)
            with service.db.transaction() as c:
                c.execute(
                    "INSERT INTO maintenance VALUES('last_backup',?) ON CONFLICT(name) DO UPDATE SET value=excluded.value",
                    (timestamp(service.clock()),),
                )
                c.execute(
                    "INSERT INTO maintenance VALUES('last_backup_file',?) ON CONFLICT(name) DO UPDATE SET value=excluded.value",
                    (name,),
                )
                c.execute("DELETE FROM maintenance WHERE name='last_backup_error'")
                service.db.audit(
                    service.clock(), actor, "backup_created", details={"file": name, **report}, connection=c
                )
            # Only our validated backup filenames inside this directory are eligible for retention.
            backups = sorted(
                directory.glob("score-????????-??????-????????.sqlite3"), key=lambda p: p.stat().st_mtime, reverse=True
            )
            for old in backups[policy.backup_keep_count :]:
                if old.parent.resolve() == directory.resolve():
                    old.unlink()
            return {"file": name, **report}
        finally:
            if pending.exists():
                pending.unlink()


def restore_backup(source, destination_dir):
    """Restore to a NEW data directory; never overwrite an active or existing database."""
    source, destination_dir = source.resolve(), destination_dir.resolve()
    report = verify_database(source)
    destination_dir.mkdir(parents=True, exist_ok=True)
    destination = destination_dir / "score.sqlite3"
    with FileLock(destination_dir / "locks", "schema"):
        if destination.exists() or destination.with_name("score.sqlite3-wal").exists():
            raise ValueError("Destination already contains a database; restore to a new directory")
        pending = destination_dir / ("restore-" + uuid4().hex + ".pending")
        try:
            with source.open("rb") as src, pending.open("xb") as dst:
                import shutil

                shutil.copyfileobj(src, dst)
                dst.flush()
                os.fsync(dst.fileno())
            verify_database(pending)
            # A backup must not resurrect active player/admin logins.
            c = sqlite3.connect(pending)
            try:
                c.execute("PRAGMA foreign_keys=ON")
                with c:
                    c.execute("DELETE FROM sessions")
                    c.execute("DELETE FROM admin_sessions")
                    c.execute("UPDATE service_tokens SET revoked_at=?", (time.time(),))
            finally:
                c.close()
            pending.replace(destination)
        finally:
            if pending.exists():
                pending.unlink()
    return report


@asynccontextmanager
async def start_maintenance(service, enabled=True):
    async def loop():
        while True:
            try:
                await run_in_threadpool(service.sweep)
                policy, _ = await run_in_threadpool(service.db.policy)

                def last_backup():
                    from .contracts import parse_utc

                    with service.db.read() as c:
                        row = c.execute("SELECT value FROM maintenance WHERE name='last_backup'").fetchone()
                    return parse_utc(row[0]).timestamp() if row else 0

                last = await run_in_threadpool(last_backup)
                if policy.backup_interval_hours and service.clock() - last >= policy.backup_interval_hours * 3600:
                    await run_in_threadpool(backup, service)
            except (OSError, ValueError, sqlite3.Error, ApiProblem) as error:
                error_type = type(error).__name__
                LOG.error("maintenance_failed type=%s", error_type)
                try:

                    def record():
                        with service.db.transaction() as c:
                            c.execute(
                                "INSERT INTO maintenance VALUES('last_backup_error',?) ON CONFLICT(name) DO UPDATE SET value=excluded.value",
                                (timestamp(service.clock()) + " " + error_type,),
                            )

                    await run_in_threadpool(record)
                except sqlite3.Error:
                    pass
            await asyncio.sleep(15)

    task = asyncio.create_task(loop()) if enabled else None
    try:
        yield
    finally:
        if task:
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass
