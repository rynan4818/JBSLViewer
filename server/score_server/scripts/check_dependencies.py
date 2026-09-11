"""Offline check so an already provisioned Windows server starts without PyPI."""

from importlib.metadata import version
from pathlib import Path

for line in (Path(__file__).resolve().parent.parent / "requirements.txt").read_text().splitlines():
    if "==" in line:
        name, expected = line.split("==")
        if version(name) != expected:
            raise SystemExit(1)
