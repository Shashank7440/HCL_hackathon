"""Ollama client with JSON output, retry, MOCK_LLM mode, token counting (approx)."""
from __future__ import annotations
import json, time
import urllib.request
import urllib.error
from ..config import settings

class LLMError(Exception): pass

def chat_json(prompt: str, system: str = "") -> tuple[dict, int]:
    """Returns (parsed_json, tokens). MOCK_LLM returns a deterministic stub the
    validators will still check - pipeline stays testable without the model."""
    if settings.MOCK_LLM:
        return {"intent": "general", "note": "mock"}, 0
    payload = json.dumps({
        "model": settings.OLLAMA_MODEL,
        "messages": [{"role": "system", "content": system},
                     {"role": "user", "content": prompt}],
        "stream": False, "format": "json",
    }).encode()
    req = urllib.request.Request(f"{settings.OLLAMA_HOST}/api/chat", data=payload,
                                 headers={"Content-Type": "application/json"})
    last_err = None
    for _ in range(2):
        try:
            with urllib.request.urlopen(req, timeout=settings.LLM_TIMEOUT_S) as resp:
                out = json.loads(resp.read())
            text = out.get("message", {}).get("content", "{}")
            return json.loads(text), out.get("prompt_eval_count", 0) + out.get("eval_count", 0)
        except (urllib.error.URLError, json.JSONDecodeError, OSError, ValueError) as e:
            last_err = e
            time.sleep(1)
    raise LLMError(f"LLM unavailable or invalid JSON: {last_err}")

def compose_answer(verified_facts: dict) -> tuple[str, int]:
    """LLM ONLY phrases verified facts (<=2 calls/ask budget). Falls back to template upstream."""
    prompt = (
        "You are a retail support agent. Using ONLY the verified facts below, write one short, "
        "friendly answer. Do not add facts, do not compute, do not invent citations.\n"
        f"FACTS: {json.dumps(verified_facts, ensure_ascii=False)}"
    )
    out, tokens = chat_json(prompt, system="Answer as JSON: {\"answer\": \"...\"}")
    return out.get("answer", ""), tokens
