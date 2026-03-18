"""Selects best free OpenRouter models for planning and writing tasks."""

import os
import sys
import httpx

FALLBACK_MODEL = "meta-llama/llama-3.3-70b-instruct:free"

QUALITY_TIERS = [
    "gemini-2",
    "deepseek-r1",
    "llama-3.3-70b",
    "llama-3.1-70b",
    "qwen",
    "mistral-large",
]


def fetch_free_models() -> list[dict]:
    try:
        r = httpx.get(
            "https://openrouter.ai/api/v1/models",
            timeout=15,
            headers={"Authorization": f"Bearer {os.environ['OPENROUTER_API_KEY']}"},
        )
        r.raise_for_status()
        return [
            m for m in r.json().get("data", [])
            if str(m.get("pricing", {}).get("prompt", "1")) == "0"
        ]
    except Exception as e:
        print(f"Warning: failed to fetch models: {e}", file=sys.stderr)
        return []


def pick_best_model(free_models: list[dict]) -> str:
    if not free_models:
        return FALLBACK_MODEL
    for tier in QUALITY_TIERS:
        for m in free_models:
            if tier in m["id"].lower():
                return m["id"]
    return sorted(free_models, key=lambda m: m.get("context_length", 0), reverse=True)[0]["id"]


def main() -> None:
    free_models = fetch_free_models()
    model = pick_best_model(free_models)
    print(f"Selected model: {model}", file=sys.stderr)

    env_file = os.environ.get("GITHUB_ENV")
    if env_file:
        with open(env_file, "a") as f:
            f.write(f"PLANNING_MODEL={model}\n")
            f.write(f"WRITING_MODEL={model}\n")
    else:
        print(f"export PLANNING_MODEL='{model}'")
        print(f"export WRITING_MODEL='{model}'")


if __name__ == "__main__":
    main()
