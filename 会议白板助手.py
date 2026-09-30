"""一键启动电商助手的 FastAPI 后端和 Streamlit 工作台。

使用方法：在 VS Code 中运行本文件，或在任意目录执行
    python "E:\\ai应用开发项目实践\\电商助手第一版MVP\\会议白板助手.py"
依赖需预先安装到项目 .venv；服务就绪后自动打开默认浏览器。
保持终端运行，按 Ctrl+C 可关闭本脚本启动的两个服务。
"""

from __future__ import annotations

import os
import socket
import subprocess
import sys
import time
import urllib.error
import urllib.request
import webbrowser
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parent
SRC_ROOT = PROJECT_ROOT / "src"
STREAMLIT_APP = SRC_ROOT / "ecommerce_assistant" / "streamlit_app.py"
STARTUP_TIMEOUT = 45


def find_available_port(preferred: int, excluded: set[int] | None = None) -> int:
    excluded = excluded or set()
    for port in range(preferred, min(preferred + 100, 65536)):
        if port in excluded:
            continue
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
            try:
                sock.bind(("127.0.0.1", port))
            except OSError:
                continue
        return port
    raise RuntimeError(f"{preferred} 起连续 100 个端口均不可用")


def project_python() -> Path:
    executable = PROJECT_ROOT / ".venv" / (
        "Scripts/python.exe" if os.name == "nt" else "bin/python"
    )
    if executable.is_file():
        return executable
    return Path(sys.executable)


def wait_until_ready(process: subprocess.Popen, url: str, name: str) -> None:
    deadline = time.monotonic() + STARTUP_TIMEOUT
    while time.monotonic() < deadline:
        if process.poll() is not None:
            raise RuntimeError(f"{name} 提前退出，退出码 {process.returncode}")
        try:
            with urllib.request.urlopen(url, timeout=2) as response:
                if response.status == 200:
                    return
        except (urllib.error.URLError, TimeoutError, OSError):
            pass
        time.sleep(0.4)
    raise TimeoutError(f"{name} 在 {STARTUP_TIMEOUT} 秒内未就绪：{url}")


def main() -> int:
    os.chdir(PROJECT_ROOT)
    if not STREAMLIT_APP.is_file():
        raise FileNotFoundError(f"未找到 Streamlit 入口：{STREAMLIT_APP}")

    python = project_python()
    api_port = find_available_port(8084)
    ui_port = find_available_port(8501, {api_port})
    api_url = f"http://127.0.0.1:{api_port}"
    ui_url = f"http://127.0.0.1:{ui_port}"
    env = os.environ.copy()
    env["PYTHONPATH"] = os.pathsep.join(
        filter(None, [str(SRC_ROOT), env.get("PYTHONPATH")])
    )
    env["API_BASE_URL"] = api_url
    env["STREAMLIT_BROWSER_GATHER_USAGE_STATS"] = "false"

    if api_port != 8084:
        print(f"端口 8084 已占用，后端改用 {api_port}", flush=True)
    if ui_port != 8501:
        print(f"端口 8501 已占用，前端改用 {ui_port}", flush=True)

    processes: list[subprocess.Popen] = []
    try:
        api = subprocess.Popen(
            [str(python), "-m", "uvicorn", "ecommerce_assistant.api.service:app",
             "--host", "127.0.0.1", "--port", str(api_port)],
            cwd=PROJECT_ROOT,
            env=env,
        )
        processes.append(api)
        wait_until_ready(api, f"{api_url}/info", "FastAPI")

        ui = subprocess.Popen(
            [str(python), "-m", "streamlit", "run", str(STREAMLIT_APP),
             "--server.address=127.0.0.1", f"--server.port={ui_port}",
             "--server.headless=true"],
            cwd=PROJECT_ROOT,
            env=env,
        )
        processes.append(ui)
        wait_until_ready(ui, f"{ui_url}/_stcore/health", "Streamlit")

        print(f"后端已就绪：{api_url}/info", flush=True)
        print(f"前端已就绪：{ui_url}", flush=True)
        if not webbrowser.open(ui_url):
            print(f"浏览器未自动打开，请手动访问 {ui_url}", flush=True)
        print("按 Ctrl+C 关闭本次启动的服务。", flush=True)
        while all(process.poll() is None for process in processes):
            time.sleep(0.5)
        raise RuntimeError("服务意外退出")
    except KeyboardInterrupt:
        print("正在关闭服务...", flush=True)
        return 0
    finally:
        for process in reversed(processes):
            if process.poll() is None:
                process.terminate()
        for process in reversed(processes):
            try:
                process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait()


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (FileNotFoundError, RuntimeError, TimeoutError) as exc:
        print(f"启动失败：{exc}", file=sys.stderr)
        raise SystemExit(1) from exc
