from __future__ import annotations

import os

import httpx
from dotenv import load_dotenv

load_dotenv()

DEFAULT_MODEL = "gpt-5.6-sol"


def get_llm_config() -> tuple[str, str, str]:
    base_url = (os.getenv("OPENAI_BASE_URL") or "https://aihub.top/v1").rstrip("/")
    model = os.getenv("OPENAI_MODEL") or DEFAULT_MODEL
    api_key = os.getenv("OPENAI_API_KEY") or ""
    return base_url, model, api_key


def get_model_candidates() -> list[str]:
    """工作台模型下拉框的候选清单。

    来源为 OPENAI_MODELS（逗号分隔）；未配置时回退到 OPENAI_MODEL 单值。
    顺序即下拉框顺序，重复项去重保序。
    """
    raw = os.getenv("OPENAI_MODELS") or ""
    names = [item.strip() for item in raw.split(",") if item.strip()]
    if not names:
        names = [get_llm_config()[1]]

    seen: set[str] = set()
    unique: list[str] = []
    for name in names:
        if name not in seen:
            seen.add(name)
            unique.append(name)
    return unique


def list_remote_models() -> list[str]:
    """向中转站拉取全部可用模型 id。

    任何失败（无 key、网络不可达、非 200、响应结构不符）一律返回空列表，
    由调用方回退到 get_model_candidates()，不在这一层抛异常。
    """
    base_url, _, api_key = get_llm_config()
    if not api_key:
        return []

    try:
        response = httpx.get(
            f"{base_url}/models",
            headers={"Authorization": f"Bearer {api_key}"},
            timeout=30,
        )
        response.raise_for_status()
        payload = response.json()
    except Exception:
        return []

    if not isinstance(payload, dict):
        return []

    items = payload.get("data") or payload.get("models") or []
    if not isinstance(items, list):
        return []

    ids = []
    for item in items:
        model_id = item.get("id") if isinstance(item, dict) else item
        if model_id:
            ids.append(str(model_id))
    return sorted(set(ids))


def call_llm(prompt: str, system_prompt: str | None = None, model: str | None = None) -> str:
    base_url, default_model, api_key = get_llm_config()
    if not api_key:
        return ""

    messages: list[dict[str, str]] = []
    if system_prompt:
        messages.append({"role": "system", "content": system_prompt})
    messages.append({"role": "user", "content": prompt})

    payload = {
        "model": model or default_model,
        "messages": messages,
        "temperature": 0.2,
        "max_tokens": 300,
    }

    try:
        response = httpx.post(
            f"{base_url}/chat/completions",
            headers={
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json",
            },
            json=payload,
            timeout=60,
        )
        response.raise_for_status()
        data = response.json()
        return data["choices"][0]["message"]["content"].strip()
    except Exception:
        return ""
