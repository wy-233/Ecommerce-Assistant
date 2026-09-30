from __future__ import annotations

import importlib.util
import socket
from pathlib import Path


SCRIPT = Path(__file__).resolve().parents[1] / "会议白板助手.py"
SPEC = importlib.util.spec_from_file_location("project_launcher", SCRIPT)
assert SPEC and SPEC.loader
launcher = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(launcher)


def test_launcher_uses_its_own_directory() -> None:
    assert launcher.PROJECT_ROOT == SCRIPT.parent
    assert launcher.STREAMLIT_APP.is_file()


def test_port_conflict_selects_next_available_port() -> None:
    with socket.socket() as occupied:
        occupied.bind(("127.0.0.1", 0))
        port = occupied.getsockname()[1]
        chosen = launcher.find_available_port(port)
        assert port < chosen <= port + 100


def test_excluded_port_is_not_selected() -> None:
    with socket.socket() as available:
        available.bind(("127.0.0.1", 0))
        port = available.getsockname()[1]
    assert launcher.find_available_port(port, {port}) != port
