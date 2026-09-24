# syntax=docker/dockerfile:1

# 镜像源：默认走阿里云 PyPI 镜像。
# 原因：本机 Docker Desktop 配了静态系统代理（127.0.0.1:7897），容器出网全部经过它，
# 实测经代理拉 pypi.org 只有 ~65 KB/s，还会整片超时；国内镜像走直连约 346 KB/s。
# 注：清华 TUNA 与中科大镜像对 uv 的 wheel 返回 403（2026-09 实测），故不选。
# 换源：docker build --build-arg PYPI_MIRROR=https://mirrors.cloud.tencent.com/pypi/simple/ .
ARG PYPI_MIRROR=https://mirrors.aliyun.com/pypi/simple/

# =============================================================================
# 阶段 1：依赖 —— 只复制依赖清单，装完即弃，改源码不必重装依赖
# =============================================================================
FROM python:3.12-slim AS deps

ARG PYPI_MIRROR

# pip 与 uv 共用同一个镜像；uv 两套变量名都设，兼容新旧版本。
ENV PIP_INDEX_URL=${PYPI_MIRROR} \
    UV_DEFAULT_INDEX=${PYPI_MIRROR} \
    UV_INDEX_URL=${PYPI_MIRROR}

# 与本地开发用同一套解析器读同一个 uv.lock，保证容器内外依赖版本一致。
# 从 PyPI 装而不是 COPY 官方 uv 镜像，避免再引入一个镜像仓库。
RUN pip install --no-cache-dir uv

ENV UV_LINK_MODE=copy \
    UV_COMPILE_BYTECODE=1 \
    UV_PYTHON_DOWNLOADS=never \
    UV_PROJECT_ENVIRONMENT=/opt/venv

WORKDIR /app

COPY pyproject.toml uv.lock ./

# uv.lock 记的是 PyPI 的绝对下载地址（1018 条 files.pythonhosted.org），
# `uv sync --frozen` 会直接照抄这些 URL，**不走** PIP_INDEX_URL / UV_DEFAULT_INDEX，
# 所以在国内会绕过镜像直连境外、整片超时。这里只把下载域名换成同路径结构的镜像域名，
# 版本与 sha256 哈希一字不动 —— 锁文件对「装哪个版本、校验哪个哈希」的约束力不变，
# 换的只是「从哪台机器取文件」。阿里云 /pypi/packages/... 与 PyPI /packages/... 同构。
# 若改回官方源（PYPI_MIRROR=https://pypi.org/simple/），此处替换是恒等变换。
RUN FILE_BASE="${PYPI_MIRROR%/simple/}" \
 && sed -i "s#https://files\.pythonhosted\.org/#${FILE_BASE}/#g" uv.lock \
 && sed -i "s#https://pypi\.org/simple#${PYPI_MIRROR%/}#g" uv.lock \
 && if grep -qE "files\.pythonhosted\.org|pypi\.org" uv.lock; then \
        echo "ERROR: uv.lock 里仍有直连境外的下载地址，改源不完整" >&2; exit 1; \
    fi \
 && echo "uv.lock 下载地址已改写为 ${FILE_BASE}"

RUN uv sync --frozen --no-install-project

# =============================================================================
# 阶段 2：运行
# =============================================================================
FROM python:3.12-slim AS runtime

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PYTHONPATH=/app/src \
    PATH="/opt/venv/bin:$PATH" \
    ECOMMERCE_DB_PATH=/app/data/db/ecommerce_assistant.db \
    HOME=/home/appuser

COPY --from=deps /opt/venv /opt/venv

WORKDIR /app

COPY pyproject.toml uv.lock README.md ./
COPY src/ ./src/
COPY data/ ./data/
COPY frontend/ ./frontend/

# 演示库落盘目录，运行时由 named volume 覆盖（见 docker-compose.yml），
# 因此重建容器不会丢数据；属主交给非 root 用户，容器内才写得进去。
RUN useradd --create-home --uid 10001 appuser \
    && mkdir -p /app/data/db \
    && chown -R appuser:appuser /app/data

USER appuser

EXPOSE 8084 8501 5500

# 默认起后端；看板与 Web 前端在 compose 里用各自的 command 覆盖
CMD ["python", "src/run_service.py"]
