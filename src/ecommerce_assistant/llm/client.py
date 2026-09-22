from __future__ import annotations

import os

import httpx
from dotenv import load_dotenv

load_dotenv()


def get_llm_config() -> tuple[str, str, str]:
    base_url = (os.getenv("OPENAI_BASE_URL") or "https://aihub.top/v1").rstrip("/")
    model = os.getenv("OPENAI_MODEL") or "gpt-5.2"
    api_key = os.getenv("OPENAI_API_KEY") or ""
    return base_url, model, api_key


def call_llm(prompt: str, system_prompt: str | None = None) -> str:
    base_url, model, api_key = get_llm_config()
    if not api_key:
        return ""

    messages: list[dict[str, str]] = []
    if system_prompt:
        messages.append({"role": "system", "content": system_prompt})
    messages.append({"role": "user", "content": prompt})

    payload = {
        "model": model,
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
