from __future__ import annotations

import argparse
import asyncio
import getpass
import logging
import os
import signal
import socket
from contextlib import contextmanager
from logging.handlers import RotatingFileHandler
from pathlib import Path

import uvicorn

from .admin import create_admin
from .api import create_api
from .config import Config, ROOT
from .database import dumps
from .locks import FileLock
from .maintenance import backup, restore_backup, verify_database
from .security import Security
from .service import Service


def configure_logging(directory):
    directory.mkdir(parents=True, exist_ok=True)
    logger = logging.getLogger("jbsl_score")
    logger.setLevel(logging.INFO)
    formatter = logging.Formatter("%(asctime)s %(levelname)s %(message)s")
    disk = RotatingFileHandler(directory / "server.log", maxBytes=5 * 1024 * 1024, backupCount=5, encoding="utf-8")
    disk.setFormatter(formatter)
    console = logging.StreamHandler()
    console.setFormatter(formatter)
    logger.handlers[:] = [disk, console]
    logger.propagate = False
    # Provider URLs may contain ticket/key parameters. Never enable their request logs.
    for name in ("httpx", "httpcore"):
        logging.getLogger(name).setLevel(logging.WARNING)


class ManagedServer(uvicorn.Server):
    @contextmanager
    def capture_signals(self):
        # A single supervisor controls both listeners and any in-flight uploads.
        yield

    async def serve(self, sockets=None):
        self._shutdown_started = False
        try:
            await super().serve(sockets=sockets)
        finally:
            # uvicorn 0.35 can return after startup when a stop arrived meanwhile.
            if self.started and not self._shutdown_started:
                self.should_exit = True
                await self.shutdown(sockets=sockets)

    async def shutdown(self, sockets=None):
        self._shutdown_started = True
        active = tuple(self.server_state.tasks)
        await super().shutdown(sockets=sockets)
        if any(task.cancelled() for task in active) or getattr(self.lifespan, "shutdown_failed", False):
            raise RuntimeError("Listener shutdown did not complete cleanly")


async def _serve_guarded(server, sock):
    try:
        await server.serve(sockets=[sock])
    except (SystemExit, KeyboardInterrupt) as exc:
        # BaseException escaping an asyncio Task can abort its siblings immediately.
        raise RuntimeError("Listener aborted") from exc


async def supervise(servers, sockets, *, shutdown_timeout, ready, log, startup_timeout=30):
    """Own signals and all listener tasks; only an explicit stop is successful."""
    stopped = asyncio.Event()
    previous = {}
    tasks = []
    cleanup_error = None

    def stop(signum, _frame):
        if not stopped.is_set():
            log(f"stopping signal={signal.Signals(signum).name}")
        stopped.set()
        for server in servers:
            server.should_exit = True

    try:
        for sig in (signal.SIGINT, signal.SIGTERM, *([signal.SIGBREAK] if hasattr(signal, "SIGBREAK") else [])):
            previous[sig] = signal.signal(sig, stop)
        tasks = [asyncio.create_task(_serve_guarded(server, sock)) for server, sock in zip(servers, sockets)]
        deadline = asyncio.get_running_loop().time() + startup_timeout
        while not stopped.is_set():
            if any(task.done() for task in tasks):
                raise RuntimeError("A listener stopped during startup")
            if all(server.started for server in servers):
                ready()
                break
            if asyncio.get_running_loop().time() >= deadline:
                raise RuntimeError("Listener startup timed out")
            await asyncio.sleep(.05)
        if not stopped.is_set():
            stop_task = asyncio.create_task(stopped.wait())
            try:
                await asyncio.wait([*tasks, stop_task], return_when=asyncio.FIRST_COMPLETED)
                if not stopped.is_set():
                    raise RuntimeError("A listener stopped unexpectedly")
            finally:
                stop_task.cancel()
                await asyncio.gather(stop_task, return_exceptions=True)
    finally:
        try:
            for server in servers:
                server.should_exit = True
            if tasks:
                done, pending = await asyncio.wait(tasks, timeout=shutdown_timeout)
                if pending:
                    cleanup_error = RuntimeError("Listener shutdown timed out")
                    log("shutdown_timeout; cancelling unfinished listeners")
                    for task in pending:
                        task.cancel()
                    cancelled, pending = await asyncio.wait(pending, timeout=1)
                    done |= cancelled
                outcomes = await asyncio.gather(*done, return_exceptions=True)
                if any(isinstance(outcome, BaseException) for outcome in outcomes):
                    cleanup_error = cleanup_error or RuntimeError("Listener failed during startup or shutdown")
        finally:
            for server in servers:
                for listener in getattr(server, "servers", ()):
                    listener.close()
            for sock in sockets:
                sock.close()
            for sig, handler in previous.items():
                signal.signal(sig, handler)
        if cleanup_error:
            raise cleanup_error
    log("stopped cleanly")


async def serve_apps(config, api, admin, *, extra_apps=()):
    listeners = [(api, config.api_host, config.api_port), (admin, config.admin_host, config.admin_port), *extra_apps]
    servers, sockets = [], []
    try:
        for app, host, port in listeners:
            family = socket.AF_INET6 if ":" in host else socket.AF_INET
            sock = socket.socket(family, socket.SOCK_STREAM)
            try:
                if os.name == "nt":
                    sock.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1)
                else:
                    sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
                sock.bind((host, port))
                sock.listen(128)
                sock.setblocking(False)
            except BaseException:
                sock.close()
                raise
            sockets.append(sock)
            server_config = uvicorn.Config(
                app,
                host=host,
                port=port,
                access_log=False,
                server_header=False,
                proxy_headers=bool(config.trusted_proxy_ips),
                forwarded_allow_ips=config.trusted_proxy_ips,
                ssl_certfile=config.ssl_certfile or None,
                ssl_keyfile=config.ssl_keyfile or None,
                timeout_keep_alive=5,
                timeout_graceful_shutdown=config.request_timeout_seconds + 30,
                limit_concurrency=256,
                h11_max_incomplete_event_size=16384,
                log_level="warning",
            )
            servers.append(ManagedServer(server_config))

        logger = logging.getLogger("jbsl_score")
        await supervise(
            servers, sockets, shutdown_timeout=config.request_timeout_seconds + 60,
            ready=lambda: logger.info("ready api=%s admin=%s/admin/", config.api_public_url, config.admin_public_url),
            log=logger.info,
        )
    finally:
        for sock in sockets:
            sock.close()


def main(argv=None):
    parser = argparse.ArgumentParser(description="JBSL Qualifier score server")
    parser.add_argument("--config", type=Path, default=ROOT / "config.json")
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("run", help="Start the API and separate administration listener")
    sub.add_parser("init", help="Create the first administrator interactively if needed")
    admin_parser = sub.add_parser("set-admin", help="Create/reset administrator and revoke their sessions")
    admin_parser.add_argument("username")
    token_parser = sub.add_parser("create-token", help="Create/rotate a read-only jbsl-web bearer token")
    token_parser.add_argument("name")
    revoke_parser = sub.add_parser("revoke-token", help="Revoke a jbsl-web token")
    revoke_parser.add_argument("name")
    sub.add_parser("backup", help="Create and verify an online database/replay backup")
    sub.add_parser("check", help="Verify database, budgets and every stored replay")
    restore = sub.add_parser("restore", help="Restore a backup into a new data directory")
    restore.add_argument("backup", type=Path)
    restore.add_argument("destination", type=Path)
    args = parser.parse_args(argv)
    if args.command == "restore":
        print(dumps(restore_backup(args.backup, args.destination)))
        return 0
    config = Config.load(args.config)
    service = Service(config)
    security = Security(service)
    if args.command in ("init", "set-admin"):
        if args.command == "init":
            with service.db.read() as c:
                if c.execute("SELECT COUNT(*) FROM admin_users").fetchone()[0]:
                    return 0
            username = input("Admin username [admin]: ").strip() or "admin"
        else:
            username = args.username
        password = getpass.getpass("New password (12-256 characters): ")
        if password != getpass.getpass("Repeat password: "):
            raise ValueError("Passwords do not match")
        security.create_admin(username, password)
        print("Administrator saved.")
    elif args.command == "create-token":
        print("Store this token in jbsl-web; it is displayed only once:")
        print(security.create_service_token(args.name))
    elif args.command == "revoke-token":
        with service.db.transaction() as c:
            if (
                c.execute("UPDATE service_tokens SET revoked_at=? WHERE name=?", (service.clock(), args.name)).rowcount
                != 1
            ):
                raise ValueError("Token name does not exist")
            service.db.audit(
                service.clock(), "local-cli", "service_token_revoked", details={"name": args.name}, connection=c
            )
        print("Token revoked.")
    elif args.command == "backup":
        print(dumps(backup(service, "local-cli")))
    elif args.command == "check":
        print(dumps(verify_database(service.db.path)))
    else:
        with service.db.read() as c:
            if not c.execute("SELECT 1 FROM admin_users LIMIT 1").fetchone():
                raise ValueError("Run 'python -m jbsl_score init' to create the administrator first")
        # One supported runner per data directory. Tests also verify DB/locks with independent processes.
        with FileLock(service.lock_dir, "runner"):
            configure_logging(config.data_dir / "logs")
            asyncio.run(serve_apps(config, create_api(service), create_admin(service)))
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (ValueError, OSError, RuntimeError) as error:
        print(f"Startup/maintenance failed: {error}")
        raise SystemExit(1)
