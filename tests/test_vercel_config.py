from __future__ import annotations

import importlib
import os
import subprocess
import sys
import tomllib
from pathlib import Path

from fastapi import FastAPI


PROJECT_ROOT = Path(__file__).resolve().parents[1]


def test_vercel_entrypoint_imports_fastapi_app() -> None:
    config = tomllib.loads((PROJECT_ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    module_name, attribute = config["tool"]["vercel"]["entrypoint"].split(":", 1)

    assert isinstance(getattr(importlib.import_module(module_name), attribute), FastAPI)


def test_vercel_database_defaults_to_writable_tmp() -> None:
    environment = {**os.environ, "VERCEL": "1"}
    result = subprocess.run(
        [
            sys.executable,
            "-c",
            "from ecommerce_assistant.db.init_db import DEFAULT_DB_PATH; "
            "print(DEFAULT_DB_PATH.as_posix())",
        ],
        cwd=PROJECT_ROOT,
        env=environment,
        capture_output=True,
        text=True,
        check=True,
    )

    assert result.stdout.strip().endswith("/tmp/ecommerce_assistant.db")
