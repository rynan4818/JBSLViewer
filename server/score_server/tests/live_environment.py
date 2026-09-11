"""Isolated real HTTP test rig. Never imported by the production launcher."""

import argparse
import asyncio
import json
import time
from dataclasses import asdict
from pathlib import Path

from fastapi import FastAPI

from jbsl_score.__main__ import serve_apps
from jbsl_score.admin import create_admin
from jbsl_score.api import create_api
from jbsl_score.config import Config
from jbsl_score.security import Security
from jbsl_score.service import Service

from .conftest import Verifier, projection


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--data", type=Path, required=True)
    parser.add_argument("--api-port", type=int, default=19381)
    parser.add_argument("--admin-port", type=int, default=19763)
    parser.add_argument("--web-port", type=int, default=19380)
    parser.add_argument("--info", type=Path, required=True)
    args = parser.parse_args()
    config = Config(
        data_dir=args.data,
        api_port=args.api_port,
        admin_port=args.admin_port,
        api_public_url=f"http://127.0.0.1:{args.api_port}",
        admin_public_url=f"http://127.0.0.1:{args.admin_port}",
        jbsl_web_url=f"http://127.0.0.1:{args.web_port}",
    )
    fixture = FastAPI()
    data = projection(time.time())

    @fixture.get("/leaderboard/api/{league_id}")
    async def board(league_id: int):
        return data

    service = Service(config, verifier=Verifier())
    policy, revision = service.db.policy()
    service.update_policy(
        {
            **asdict(policy),
            "auth_per_minute": 600,
            "status_per_minute": 600,
            "reserve_per_minute": 600,
            "result_per_minute": 600,
            "backup_interval_hours": 0,
        },
        revision,
        "test",
        "test",
    )
    security = Security(service)
    security.create_admin("operator", "test-admin-password-2026")
    token = security.create_service_token("live-validation")
    args.info.parent.mkdir(parents=True, exist_ok=True)
    args.info.write_text(
        json.dumps(
            {"api": config.api_public_url, "admin": config.admin_public_url, "web": config.jbsl_web_url, "token": token}
        ),
        encoding="utf-8",
    )
    asyncio.run(
        serve_apps(
            config, create_api(service), create_admin(service), extra_apps=[(fixture, "127.0.0.1", args.web_port)]
        )
    )


if __name__ == "__main__":
    main()
