"""Run this server and its dedicated administration listener."""
from __future__ import annotations

import argparse
import asyncio
import contextlib
import getpass
import json
import os
import signal
import socket
import sqlite3
import sys
import warnings
from pathlib import Path

import uvicorn

from .admin_auth import AdminAuth
from .admin_server import make_apps
from .config import ROOT, load_public_url
from .control import Control


class ManagedServer(uvicorn.Server):
    # One coordinator owns Ctrl+C for all listeners (works across uvicorn versions).
    @contextlib.contextmanager
    def capture_signals(self):
        yield

    def install_signal_handlers(self):
        pass

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


def configure_admin(auth, username=None):
    initial = username is None
    if initial and auth.has_admin():
        return
    if not sys.stdin.isatty():
        raise RuntimeError("Administrator setup requires a local interactive terminal. Run start.bat init with the same --data-dir first")
    if initial:
        print("Create the first JBSL WEB Relay administrator. No default password is provided.", flush=True)
        username = input("Admin username [admin]: ") or "admin"
    # Do not allow getpass to fall back to echoed input when a terminal is unavailable.
    with warnings.catch_warnings():
        warnings.simplefilter("error", getpass.GetPassWarning)
        password = getpass.getpass("New password (12-256 characters): ")
        confirmation = getpass.getpass("Confirm password: ")
    if password != confirmation:
        raise ValueError("Passwords do not match; no administrator was changed")
    changed = auth.set_admin(username, password, only_if_empty=initial)
    print("Administrator saved. Existing sessions for this user were revoked." if changed else "An administrator is already configured.", flush=True)


async def serve(args):
    public_url = load_public_url()
    ports = [args.admin_port, args.api_port]
    if len(set(ports)) != 2 or any(not 1024 <= p <= 65535 for p in ports):
        raise ValueError("Specify two distinct ports between 1024 and 65535")
    if not 5 <= args.shutdown_timeout <= 300:
        raise ValueError("shutdown-timeout must be between 5 and 300 seconds")
    sockets, servers = [], []
    try:
        # Reserve every port before opening databases or starting any listener.
        for port in ports:
            sock = socket.socket()
            sockets.append(sock)
            if os.name == "nt":
                sock.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1)
            else:
                sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            sock.bind(("127.0.0.1", port))
            sock.listen(128)
            sock.setblocking(False)
        auth = AdminAuth(args.data_dir / "admin_auth.sqlite3")
        configure_admin(auth)
        control = Control(args.data_dir, admin_port=args.admin_port, proxy_port=args.api_port, public_url=public_url)
        if args.offline:
            control.commit(lambda state: state["behavior"].update(upstream_mode="snapshot"))
        apps = make_apps(control)
        for app in apps:
            servers.append(ManagedServer(uvicorn.Config(app, host="127.0.0.1", access_log=False, log_level="warning",
                                                       proxy_headers=True, forwarded_allow_ips="127.0.0.1",
                                                       timeout_graceful_shutdown=args.shutdown_timeout)))
        def ready():
            print("ready JBSL WEB Relay / TEST ONLY", flush=True)
            for role, url in control.urls.items():
                print(f"{role}: {url}" + ("/admin/" if role == "admin" else "/docs"), flush=True)
            if public_url:
                print(f"public: {public_url}/admin/ (config.json)", flush=True)
            if args.ready_file:
                args.ready_file.parent.mkdir(parents=True, exist_ok=True)
                args.ready_file.write_text(json.dumps(control.urls), encoding="utf-8")
        await supervise(servers, sockets, shutdown_timeout=args.shutdown_timeout + 30,
                        ready=ready, log=lambda message: print(message, flush=True))
    finally:
        for sock in sockets:
            sock.close()


def main(argv=None):
    parser = argparse.ArgumentParser(description="JBSLViewer local mock control; no game DLLs required")
    parser.add_argument("command", nargs="?", choices=("run", "init", "set-admin"), default="run",
                        help="run (default), initialize the first administrator, or set an administrator password")
    parser.add_argument("username", nargs="?", help="Administrator username for set-admin")
    parser.add_argument("--admin-port", type=int, default=18764)
    parser.add_argument("--api-port", "--proxy-port", dest="api_port", type=int, default=18080)
    parser.add_argument("--data-dir", type=Path, default=ROOT / "data")
    parser.add_argument("--shutdown-timeout", type=int, default=90,
                        help="Seconds to drain HTTP requests on stop (5-300; default 90)")
    parser.add_argument("--offline", action="store_true", help="Use saved upstream responses")
    parser.add_argument("--ready-file", type=Path, help=argparse.SUPPRESS)
    args = parser.parse_args(argv)
    if (args.command == "set-admin") != (args.username is not None):
        parser.error("set-admin requires a username; other commands do not accept one")
    try:
        if args.command == "run":
            asyncio.run(serve(args))
        else:
            configure_admin(AdminAuth(args.data_dir / "admin_auth.sqlite3"), args.username)
    except (EOFError, KeyboardInterrupt, getpass.GetPassWarning):
        parser.exit(1, "Administrator setup cancelled. No unauthenticated server was started.\n")
    except (OSError, ValueError, RuntimeError, sqlite3.Error) as exc:
        parser.exit(1, f"Cannot start or configure local mock servers: {exc}\nCheck ports, config.json and the data directory. No existing service was stopped.\n")


if __name__ == "__main__":
    main()
