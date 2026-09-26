"""LLM 호출 (선택). OpenAI 호환 Chat Completions 엔드포인트 하나로 통일.

환경변수 (.env.example 참고):
  OPENAI_BASE_URL  기본 https://api.openai.com/v1  (Ollama: http://localhost:11434/v1, vLLM 등)
  OPENAI_API_KEY   로컬 오픈 LLM 이면 비워도 됨
  LLM_MODEL        예: gpt-4o-mini, qwen2.5:7b-instruct
규칙: LLM 은 '글(계획 초안·서술)'만 쓴다. 숫자 계산은 항상 core.estimators.
"""

from __future__ import annotations

import os

import requests


def configured() -> bool:
    return bool(os.getenv("LLM_MODEL")) and bool(
        os.getenv("OPENAI_API_KEY") or os.getenv("OPENAI_BASE_URL")
    )


def chat(system: str, user: str, temperature: float = 0.2, timeout: int = 120) -> str:
    base = os.getenv("OPENAI_BASE_URL") or "https://api.openai.com/v1"
    key = os.getenv("OPENAI_API_KEY", "")
    r = requests.post(
        f"{base.rstrip('/')}/chat/completions",
        headers={"Authorization": f"Bearer {key}"} if key else {},
        json={
            "model": os.environ["LLM_MODEL"],
            "temperature": temperature,
            "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}],
        },
        timeout=timeout,
    )
    r.raise_for_status()
    return r.json()["choices"][0]["message"]["content"].strip()


def strip_fence(text: str) -> str:
    """```yaml ... ``` 코드펜스 제거."""
    t = text.strip()
    if t.startswith("```"):
        t = t.split("\n", 1)[1] if "\n" in t else ""
        t = t.rsplit("```", 1)[0]
    return t.strip()
