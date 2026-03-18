"""Thin LLM client. Change BASE_URL and build_headers() to swap providers."""

import os
import sys
import time
import httpx

BASE_URL = "https://openrouter.ai/api/v1/chat/completions"
MODELS_URL = "https://openrouter.ai/api/v1/models"


def build_headers(api_key: str) -> dict:
    return {
        "Authorization": f"Bearer {api_key}",
        "HTTP-Referer": "https://github.com/YOUR_USERNAME/mealplan",
        "X-Title": "Meal Planner Agent",
    }


def fetch_free_model_ids(api_key: str) -> list[str]:
    try:
        r = httpx.get(MODELS_URL, headers=build_headers(api_key), timeout=15)
        r.raise_for_status()
        return [
            m["id"] for m in r.json().get("data", [])
            if str(m.get("pricing", {}).get("prompt", "1")) == "0"
        ]
    except Exception as e:
        print(f"  Could not fetch model list: {e}", file=sys.stderr)
        return []


def _try_model(system: str, prompt: str, model: str, headers: dict, max_tokens: int) -> str | None:
    """Return text on success, None on 429, raise on other errors."""
    payload = {
        "model": model,
        "messages": [
            {"role": "system", "content": system},
            {"role": "user", "content": prompt},
        ],
        "temperature": 0.7,
        "max_tokens": max_tokens,
    }
    r = httpx.post(BASE_URL, json=payload, headers=headers, timeout=180)
    if r.status_code == 429:
        print(f"  {model}: rate limited", file=sys.stderr)
        return None
    r.raise_for_status()
    return r.json()["choices"][0]["message"]["content"].strip()


STATIC_FALLBACKS = [
    "meta-llama/llama-3.3-70b-instruct:free",
    "google/gemma-3-27b-it:free",
    "mistralai/mistral-small-3.1-24b-instruct:free",
]


def call_llm(system: str, prompt: str, preferred_model: str, max_tokens: int = 4000) -> str:
    api_key = os.environ["OPENROUTER_API_KEY"]
    headers = build_headers(api_key)
    live_free = fetch_free_model_ids(api_key)

    seen: set[str] = set()
    candidates: list[str] = []
    for m in [preferred_model] + live_free + STATIC_FALLBACKS:
        if m not in seen:
            seen.add(m)
            candidates.append(m)

    for candidate in candidates:
        print(f"  Trying: {candidate}", file=sys.stderr)
        try:
            result = _try_model(system, prompt, candidate, headers, max_tokens)
            if result is not None:
                print(f"  Success: {candidate}", file=sys.stderr)
                return result
            time.sleep(15)
        except Exception as e:
            print(f"  {candidate} error: {e}, skipping", file=sys.stderr)

    raise RuntimeError("All models exhausted")
