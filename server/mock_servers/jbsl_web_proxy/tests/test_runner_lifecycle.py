import asyncio
import signal

import pytest

from mock_servers.jbsl_web_proxy.__main__ import supervise


class Socket:
    closed = False

    def close(self):
        self.closed = True


class Server:
    def __init__(self, mode="normal"):
        self.mode = mode
        self.started = False
        self.should_exit = False
        self.finished = False

    async def serve(self, sockets):
        try:
            if self.mode == "systemexit":
                raise SystemExit(3)
            if self.mode == "startup_error":
                raise ValueError("startup failure")
            if self.mode != "startup_hang":
                self.started = True
            while not self.should_exit:
                await asyncio.sleep(.01)
                if self.mode == "return":
                    await asyncio.sleep(.1)
                    return
                if self.mode == "exception":
                    await asyncio.sleep(.1)
                    raise ValueError("listener failed")
            if self.mode == "shutdown_error":
                raise RuntimeError("shutdown failure")
            if self.mode == "shutdown_hang":
                await asyncio.Event().wait()
        finally:
            self.finished = True


def run_case(monkeypatch, mode, *, stop_delay=None):
    handlers = {signal.SIGINT: object(), signal.SIGTERM: object()}
    if hasattr(signal, "SIGBREAK"):
        handlers[signal.SIGBREAK] = object()
    original = handlers.copy()

    def install(sig, handler):
        old = handlers[sig]
        handlers[sig] = handler
        return old

    monkeypatch.setattr(signal, "signal", install)
    monkeypatch.setattr(signal, "getsignal", lambda sig: handlers[sig])
    servers = [Server(mode), Server()]
    sockets = [Socket(), Socket()]
    events = []

    async def run():
        if stop_delay is not None:
            asyncio.get_running_loop().call_later(stop_delay, lambda: handlers[signal.SIGTERM](signal.SIGTERM, None))
        await supervise(servers, sockets, shutdown_timeout=.1, startup_timeout=.1,
                        ready=lambda: events.append("ready"), log=events.append)
    try:
        asyncio.run(run())
    finally:
        assert all(sock.closed for sock in sockets)
        assert all(server.finished for server in servers)
        assert handlers == original
    return events


def test_normal_stop_waits_for_both_and_restores_handlers(monkeypatch):
    events = run_case(monkeypatch, "normal", stop_delay=.08)
    assert events[0] == "ready"
    assert events[-1] == "stopped cleanly"


def test_stop_during_startup_is_normal_without_ready(monkeypatch):
    events = run_case(monkeypatch, "startup_hang", stop_delay=.02)
    assert "ready" not in events
    assert events[-1] == "stopped cleanly"


@pytest.mark.parametrize("mode", ["return", "exception", "systemexit", "startup_error", "startup_hang"])
def test_listener_failure_stops_sibling_and_is_not_success(monkeypatch, mode):
    with pytest.raises(RuntimeError):
        run_case(monkeypatch, mode)


@pytest.mark.parametrize("mode", ["shutdown_error", "shutdown_hang"])
def test_failed_shutdown_is_not_success(monkeypatch, mode):
    with pytest.raises(RuntimeError):
        run_case(monkeypatch, mode, stop_delay=.08)
