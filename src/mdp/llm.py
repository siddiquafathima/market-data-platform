"""Optional LLM access through any OpenAI-compatible chat endpoint.

Set LLM_API_KEY, LLM_BASE_URL and LLM_MODEL to enable it. Without them every AI feature falls
back to deterministic rules, so the platform never *depends* on a model being available.
"""
from __future__ import annotations

import logging
import os

import requests

log = logging.getLogger("mdp")


def llm_configured() -> bool:
    return all(os.getenv(k) for k in ("LLM_API_KEY", "LLM_BASE_URL", "LLM_MODEL"))


def chat(messages: list[dict], timeout: int = 30) -> str | None:
    """Return the model's reply, or None if not configured or the call fails."""
    if not llm_configured():
        return None
    try:
        resp = requests.post(
            os.environ["LLM_BASE_URL"].rstrip("/") + "/chat/completions",
            headers={"Authorization": f"Bearer {os.environ['LLM_API_KEY']}"},
            json={"model": os.environ["LLM_MODEL"], "messages": messages, "temperature": 0.1, "max_tokens": 300},
            timeout=timeout,
        )
        resp.raise_for_status()
        return resp.json()["choices"][0]["message"]["content"].strip() or None
    except Exception as exc:  # network/model errors must never break the pipeline
        log.warning("LLM call failed: %s", exc)
        return None