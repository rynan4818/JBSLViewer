"""Run this server and its dedicated administration listener."""
from __future__ import annotations

import argparse
import asyncio
import contextlib
import json
import os
import signal
import socket
from pathlib import Path

import uvicorn

from .config import ROOT
from .control import Control
from .admin_server import make_apps


class ManagedServer(uvicorn.Server):
    # One coordinator owns Ctrl+C for all listeners (works across uvicorn versions).
    @contextlib.contextmanager
    def capture_signals(self):
        yield

    def install_signal_handlers(self):
        pass


async def serve(args):
    ports = [args.admin_port, args.api_port]
    if len(set(ports)) != 2 or any(not 1024 <= p <= 65535 for p in ports):
        raise ValueError("Specify two distinct ports between 1024 and 65535")
    sockets, servers = [], []
    try:
        # Reserve every port before opening databases or starting any listener.
        for port in ports:
            sock = socket.socket()
            sockets.append(sock)
            if os.name == "nt":
                sock.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1)
            sock.bind(("127.0.0.1", port))
            sock.listen(128)
            sock.setblocking(False)
        control = Control(args.data_dir, admin_port=args.admin_port, score_port=args.api_port)
        apps = make_apps(control)
        for app in apps:
            servers.append(ManagedServer(uvicorn.Config(app, host="127.0.0.1", access_log=False, log_level="warning", timeout_graceful_shutdown=3)))
        def stop(*_):
            for server in servers:
                server.should_exit = True
        signal.signal(signal.SIGINT, stop)
        if hasattr(signal, "SIGTERM"):
            signal.signal(signal.SIGTERM, stop)
        if hasattr(signal, "SIGBREAK"):
            signal.signal(signal.SIGBREAK, stop)
        tasks = [asyncio.create_task(server.serve(sockets=[sock])) for server, sock in zip(servers, sockets)]
        for _ in range(200):
            if all(s.started for s in servers):
                break
            if any(task.done() for task in tasks):
                raise RuntimeError("A listener stopped during startup")
            await asyncio.sleep(.05)
        else:
            raise RuntimeError("Startup timed out")
        print("JBSL Mock / TEST ONLY - Ctrl+C stops this API and its admin", flush=True)
        for role, url in control.urls.items():
            print(f"{role}: {url}" + ("/admin/" if role == "admin" else "/docs"), flush=True)
        if args.ready_file:
            args.ready_file.parent.mkdir(parents=True, exist_ok=True)
            args.ready_file.write_text(json.dumps(control.urls), encoding="utf-8")
        await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)
        stop()
        await asyncio.gather(*tasks)
    finally:
        for server in servers:
            server.should_exit = True
        for sock in sockets:
            sock.close()


def main():
    parser = argparse.ArgumentParser(description="JBSLViewer local mock control; no game DLLs required")
    parser.add_argument("--admin-port", type=int, default=18765)
    parser.add_argument("--api-port", "--score-port", dest="api_port", type=int, default=18082)
    parser.add_argument("--data-dir", type=Path, default=ROOT / "data")
    parser.add_argument("--ready-file", type=Path, help=argparse.SUPPRESS)
    args = parser.parse_args()
    try:
        asyncio.run(serve(args))
    except (OSError, ValueError, RuntimeError) as exc:
        parser.exit(1, f"Cannot start local mock servers: {exc}\nCheck ports and control.json. No existing service was stopped.\n")


if __name__ == "__main__":
    main()
