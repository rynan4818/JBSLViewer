"""Exercise the actual start.bat/production authentication in an isolated data directory."""

import json
import os
import signal
import socket
import subprocess
import sys
import time
from dataclasses import asdict
from pathlib import Path

import httpx

from jbsl_score.config import Config
from jbsl_score.security import Security
from jbsl_score.service import Service

ROOT = Path(__file__).resolve().parent.parent


def production_smoke(directory):
    directory.mkdir(parents=True, exist_ok=True)
    sockets = [socket.socket(), socket.socket()]
    try:
        for sock in sockets:
            sock.bind(("127.0.0.1", 0))
        api_port, admin_port = [sock.getsockname()[1] for sock in sockets]
    finally:
        for sock in sockets:
            sock.close()
    config = Config(
        data_dir=directory / "data",
        api_port=api_port,
        admin_port=admin_port,
        api_public_url=f"http://127.0.0.1:{api_port}",
        admin_public_url=f"http://127.0.0.1:{admin_port}",
        jbsl_web_url="http://127.0.0.1:9",
        oculus_enabled=False,
    )
    service = Service(config)
    Security(service).create_admin("operator", "production-launcher-test-password")
    config_file = directory / "config.json"
    payload = asdict(config)
    payload["data_dir"] = str(config.data_dir)
    config_file.write_text(json.dumps(payload), encoding="utf-8")
    env = dict(os.environ)
    env["JBSL_CONFIG"] = str(config_file)
    env["JBSL_STEAM_API_KEY"] = ""
    env["JBSL_JBSL_WEB_TOKEN"] = ""
    env["PYTHONIOENCODING"] = "utf-8"
    command = (
        [os.environ.get("COMSPEC", "cmd.exe"), "/d", "/c", "start.bat"]
        if os.name == "nt"
        else [sys.executable, "-m", "jbsl_score", "--config", str(config_file), "run"]
    )
    kwargs = {}
    if os.name == "nt":
        kwargs["creationflags"] = subprocess.CREATE_NEW_PROCESS_GROUP
        startup = subprocess.STARTUPINFO()
        startup.dwFlags |= subprocess.STARTF_USESHOWWINDOW
        startup.wShowWindow = 0
        kwargs["startupinfo"] = startup
    with (directory / "launcher.log").open("wb") as log:
        process = subprocess.Popen(
            command, cwd=ROOT, env=env, stdin=subprocess.PIPE, stdout=log, stderr=subprocess.STDOUT, **kwargs
        )
        try:
            with httpx.Client(trust_env=False, timeout=2) as client:
                deadline = time.monotonic() + 30
                while True:
                    if process.poll() is not None:
                        raise RuntimeError("Production launcher exited before readiness")
                    try:
                        if client.get(config.api_public_url + "/readyz").status_code == 200:
                            break
                    except httpx.HTTPError:
                        pass
                    if time.monotonic() > deadline:
                        raise RuntimeError("Production launcher did not become ready")
                    time.sleep(0.1)
                login = client.post(
                    config.admin_public_url + "/admin/api/login",
                    headers={"X-JBSL-Admin": "1"},
                    json={"username": "operator", "password": "production-launcher-test-password"},
                )
                assert login.status_code == 200
                forbidden_stub = client.post(
                    config.api_public_url + "/api/v1/auth/session",
                    data={"provider": "steamTicket", "ticket": "mock-ticket", "returnUrl": "/"},
                )
                assert forbidden_stub.status_code == 503
                assert forbidden_stub.json()["error"]["code"] == "auth_provider_unavailable"
                assert "jbslq_session" not in forbidden_stub.cookies
        finally:
            if process.poll() is None:
                process.send_signal(signal.CTRL_BREAK_EVENT if os.name == "nt" else signal.SIGTERM)
                # cmd may ask whether to terminate its batch; this is the test's own process.
                try:
                    process.communicate(input=b"Y\r\n", timeout=30)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait()
                    raise RuntimeError("Production launcher did not stop gracefully")
    with httpx.Client(trust_env=False, timeout=1) as client:
        for base in (config.api_public_url, config.admin_public_url):
            try:
                client.get(base + "/")
            except httpx.HTTPError:
                continue
            raise RuntimeError("A production listener remained alive after shutdown")
    print("production-launcher: PASS", flush=True)
    return {
        "start_bat": "passed" if os.name == "nt" else "not applicable",
        "readiness": "passed",
        "admin_login": "passed",
        "stub_auth_rejected": "passed",
        "shutdown": "passed",
    }
