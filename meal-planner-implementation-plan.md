# Weekly Meal Planner — Implementation Plan

## Vision

An autonomous weekly meal planning blog hosted on GitHub Pages. Every Sunday, a GHA workflow uses free OpenRouter LLMs to generate a personalized 7-day meal plan tailored to the family's dietary needs, optimized for batch ingredient prep across two weekly prep sessions.

The output is a Hugo blog post containing:
- 7 dinners with full recipes (with variations to accommodate different diets)
- A meal prep optimization plan: what to prep on the weekend, what to prep midweek
- A consolidated grocery list

---

## Architecture

```
config/family.yaml         → family members, dietary restrictions, preferences, prep schedule
agents/model_selector.py   → picks best free OpenRouter models at runtime
agents/meal_planner.py     → generates meal plan JSON using LLM
agents/writing_agent.py    → formats meal plan JSON into Hugo markdown post
agents/history.json        → committed, rolling 8-week history of past meals (avoids repetition)
content/posts/             → Hugo posts, one per week (YYYY-MM-DD.md)
themes/mealplan/           → minimal Hugo theme, no JS, no external dependencies
.github/workflows/
  weekly-plan.yml          → cron 0 8 * * 0 (Sunday 08:00 UTC) → plan → write → build → deploy
  publish.yml              → reusable Hugo build + gh-pages deploy
```

**Pipeline:** model_selector → meal_planner (→ /tmp/meal_plan.json) → writing_agent (→ content/posts/) → Hugo build → gh-pages deploy

**Provider abstraction:** All LLM calls go through a single `call_llm(prompt, system, model, headers)` function in a shared `agents/llm.py`. Swapping providers means updating the base URL and auth header format in one place.

---

## File Specifications

### `config/family.yaml`

Family configuration committed to the repo. This is the persistent state that shapes every meal plan.

```yaml
family:
  - name: Matt
    restrictions: []
    preferences:
      - spicy food
      - asian cuisine
      - grilling
  - name: Sarah
    restrictions:
      - vegetarian
    preferences:
      - mediterranean
      - salads
  - name: Jake
    restrictions:
      - tree nut allergy
    preferences:
      - mild flavors
      - pasta
      - pizza

meal_plan:
  days:
    - Monday
    - Tuesday
    - Wednesday
    - Thursday
    - Friday
    - Saturday
    - Sunday
  meal: dinner  # currently only planning dinners

prep_sessions:
  - label: Weekend Prep
    day: Sunday
    max_hours: 3
  - label: Midweek Prep
    day: Wednesday
    max_hours: 1.5
```

**Notes:**
- `restrictions` are hard constraints (allergies, dietary choices)
- `preferences` are soft signals the LLM uses to select appealing recipes
- `days` controls how many meals are planned
- The user should edit this file to reflect their actual family before running the workflow

---

### `agents/llm.py`

Single LLM call abstraction. Provider-swappable.

```python
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
```

---

### `agents/model_selector.py`

Identical pattern to tenkai. Writes `PLANNING_MODEL` and `WRITING_MODEL` to `$GITHUB_ENV`.

```python
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
```

---

### `agents/meal_planner.py`

Reads `config/family.yaml` and `agents/history.json`, calls the LLM to generate a structured JSON meal plan, writes to `/tmp/meal_plan.json`.

**System prompt goals:**
- Generate 7 dinner recipes appropriate for the family
- Each recipe: one base version + noted variations per restricted family member
- Identify shared ingredients across recipes
- Group shared ingredient prep into the two prep sessions
- Output strict JSON

**Output JSON schema (`/tmp/meal_plan.json`):**
```json
{
  "week_of": "2026-03-22",
  "meals": [
    {
      "day": "Monday",
      "name": "Stir-Fried Tofu & Pepper Noodles",
      "serves": 3,
      "time_active_minutes": 20,
      "time_total_minutes": 30,
      "ingredients": [
        {"item": "bell peppers", "amount": "3", "unit": "whole"},
        {"item": "tofu", "amount": "400", "unit": "g"},
        {"item": "noodles", "amount": "300", "unit": "g"}
      ],
      "recipe_steps": [
        "Slice peppers (already prepped).",
        "Pan-fry tofu until golden, ~8 min.",
        "Toss with noodles and sauce."
      ],
      "variations": {
        "Matt": "Add 1 tbsp chili oil and sliced jalapeños.",
        "Jake": "Skip chili oil; serve sauce on side."
      }
    }
  ],
  "prep_sessions": [
    {
      "label": "Weekend Prep",
      "day": "Sunday",
      "tasks": [
        "Slice all bell peppers (used Mon, Wed, Fri) — store in airtight container.",
        "Cook a pot of brown rice (used Tue, Thu) — refrigerate.",
        "Marinate tofu overnight in soy-ginger sauce."
      ]
    },
    {
      "label": "Midweek Prep",
      "day": "Wednesday",
      "tasks": [
        "Roast a tray of root vegetables (used Thu, Sat).",
        "Chop onions and garlic for remaining recipes."
      ]
    }
  ],
  "grocery_list": [
    {"item": "bell peppers", "total_amount": "9 whole", "used_in": ["Monday", "Wednesday", "Friday"]},
    {"item": "tofu", "total_amount": "800g", "used_in": ["Monday", "Thursday"]}
  ]
}
```

**History tracking (`agents/history.json`):**
```json
{
  "meals": [
    {"week_of": "2026-03-15", "names": ["Stir-Fried Tofu", "Lentil Soup", "..."]},
    {"week_of": "2026-03-08", "names": ["..."]}
  ]
}
```
Keep rolling 8-week window. Pass the last 8 weeks of meal names in the prompt so the LLM avoids repeating them.

**System prompt (embed in the script):**

```
You are a meal planning assistant. Generate a 7-dinner meal plan for a family.

Rules:
- Every meal must be safe for ALL family members (respect all hard restrictions absolutely)
- Where family members have conflicting preferences, design one base recipe with simple variations noted per person
- Coordinate ingredients across meals: if multiple recipes use the same ingredient, note it so prep can be batched
- Prefer seasonal, whole-food ingredients
- Recipes should be realistic weeknight dinners: active cooking time ≤ 45 minutes after prep work is done
- Do not repeat any meal from the recent history provided

Output ONLY valid JSON matching the schema provided. No commentary, no markdown fences.
```

**User prompt structure:**
```
Family:
- Matt: no restrictions. Likes spicy food, asian cuisine.
- Sarah: vegetarian. Likes mediterranean.
- Jake: tree nut allergy. Likes mild flavors, pasta.

Prep sessions:
- Sunday (Weekend Prep): up to 3 hours
- Wednesday (Midweek Prep): up to 1.5 hours

Recent meals to avoid repeating:
- Week of 2026-03-15: Stir-Fried Tofu, Lentil Soup, Pasta Primavera, ...
- Week of 2026-03-08: ...

Output JSON matching this schema exactly:
[paste the JSON schema]
```

---

### `agents/writing_agent.py`

Reads `/tmp/meal_plan.json`, formats it as a Hugo markdown post with front matter.

**Sections in the post:**
1. **This Week's Meals** — table overview (day | meal name | time)
2. **Recipes** — one H3 per day with full recipe (ingredients list, steps, variations callout)
3. **Meal Prep Plan** — two subsections (Weekend Prep / Midweek Prep) with task lists
4. **Grocery List** — consolidated, grouped by category (produce / proteins / pantry)

The writing agent should **not** call the LLM for formatting — it should template directly from the JSON. The LLM was already used in the planning step; the writing step is pure deterministic formatting.

**Front matter:**
```yaml
---
title: "Meal Plan — Week of March 22, 2026"
date: 2026-03-22
draft: false
tags: [meal-plan, weekly]
description: "7 dinners: Stir-Fried Tofu, Lentil Soup, and 5 more. Weekend prep: ~2h."
---
```

---

### `agents/history.py`

Helper module (not a standalone script). Functions:
- `load_history(path) -> list[dict]` — load history.json, return list of `{week_of, names}` dicts
- `save_history(path, week_of, meal_names)` — prepend new entry, prune to 8 weeks, write back
- `recent_meal_names(history, weeks=8) -> list[str]` — flat list of meal names for the prompt

---

### `requirements.txt`

```
httpx>=0.27
pyyaml>=6.0
```

No heavier dependencies needed — no scraping, no embeddings, no search.

---

### `.github/workflows/weekly-plan.yml`

```yaml
name: Weekly Meal Plan

on:
  schedule:
    - cron: '0 8 * * 0'   # Sunday 08:00 UTC
  workflow_dispatch:

permissions:
  contents: write

jobs:
  generate-plan:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4

      - uses: actions/setup-python@v5
        with:
          python-version: '3.12'

      - run: pip install -r requirements.txt

      - name: Guard — skip if this week's post already exists
        run: |
          # Get the most recent Sunday (including today)
          WEEK_OF=$(date -u -d "last sunday" +%Y-%m-%d 2>/dev/null || date -u -v-sun +%Y-%m-%d)
          POST="content/posts/${WEEK_OF}.md"
          echo "WEEK_OF=$WEEK_OF" >> "$GITHUB_ENV"
          if [ -f "$POST" ]; then
            echo "Post $POST already exists, skipping."
            echo "SKIP_AGENTS=true" >> "$GITHUB_ENV"
          fi

      - name: Select models
        if: env.SKIP_AGENTS != 'true'
        env:
          OPENROUTER_API_KEY: ${{ secrets.OPENROUTER_API_KEY }}
        run: python agents/model_selector.py

      - name: Generate meal plan
        if: env.SKIP_AGENTS != 'true'
        env:
          OPENROUTER_API_KEY: ${{ secrets.OPENROUTER_API_KEY }}
        run: python agents/meal_planner.py

      - name: Write Hugo post
        if: env.SKIP_AGENTS != 'true'
        run: python agents/writing_agent.py

      - name: Commit post and history
        if: env.SKIP_AGENTS != 'true'
        run: |
          git config user.name "mealplan-bot"
          git config user.email "mealplan-bot@users.noreply.github.com"
          POST="content/posts/${WEEK_OF}.md"
          git add "$POST" agents/history.json
          git commit -m "meal-plan: week of ${WEEK_OF} [skip ci]"
          git push

      - name: Create issue on failure
        if: failure()
        uses: actions/github-script@v7
        with:
          script: |
            github.rest.issues.create({
              owner: context.repo.owner,
              repo: context.repo.repo,
              title: `Meal plan failed — ${new Date().toISOString().slice(0,10)}`,
              body: `The weekly meal plan workflow failed. [View run](${context.serverUrl}/${context.repo.owner}/${context.repo.repo}/actions/runs/${context.runId})`,
              labels: ['bot-failure'],
            })

  publish:
    needs: generate-plan
    uses: ./.github/workflows/publish.yml
    secrets: inherit
```

---

### `.github/workflows/publish.yml`

Identical to tenkai's publish.yml. Reusable Hugo build + gh-pages deploy.

```yaml
name: Publish to GitHub Pages

on:
  workflow_call:
  workflow_dispatch:

permissions:
  contents: write

jobs:
  publish:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
        with:
          ref: main

      - uses: peaceiris/actions-hugo@v3
        with:
          hugo-version: '0.139.0'
          extended: false

      - run: hugo --minify

      - uses: peaceiris/actions-gh-pages@v4
        with:
          github_token: ${{ secrets.GITHUB_TOKEN }}
          publish_dir: ./public
```

---

### Hugo Theme (`themes/mealplan/`)

Minimal theme, no JS, no external dependencies. CSS variables for light/dark.

**Required layouts:**
- `layouts/_default/baseof.html` — shell with `<head>`, nav, footer
- `layouts/_default/single.html` — single post, renders `.Content`
- `layouts/_default/list.html` — index listing past weeks
- `layouts/index.html` — homepage redirects to latest post OR renders list

**Required static:**
- `static/style.css` — CSS variables, minimal typography, responsive

**`hugo.toml`:**
```toml
baseURL = "https://YOUR_USERNAME.github.io/mealplan/"
languageCode = "en-us"
title = "Weekly Meal Plan"
theme = "mealplan"

[markup.goldmark.renderer]
  unsafe = true
```

---

## Repository Initial State

Files to create before the first workflow run:

```
agents/history.json         → {"meals": []}
agents/seen.json            → not needed (meals repeat seasonally, history is fine)
config/family.yaml          → populated with real family data
```

---

## Setup Instructions (for the new repo)

1. Create a new GitHub repo (e.g. `mealplan`)
2. Enable GitHub Pages: Settings → Pages → Source: `gh-pages` branch, root `/`
3. Add secret: Settings → Secrets → `OPENROUTER_API_KEY`
4. Update `config/family.yaml` with your family's real data
5. Update `agents/llm.py`: change `HTTP-Referer` to your repo URL
6. Update `hugo.toml`: set `baseURL` to `https://YOUR_USERNAME.github.io/mealplan/`
7. Push to `main` — the workflow runs every Sunday at 08:00 UTC
8. Trigger manually via `workflow_dispatch` to generate the first post

---

## Key Design Decisions

- **No recipe web scraping** — the LLM generates complete recipes from scratch based on family config. This avoids copyright issues, rate limits, and external dependencies. The LLM has extensive recipe knowledge.
- **Single model for both steps** — planning and writing use the same model selection. The planning step does the heavy lifting (JSON generation); writing is deterministic template formatting with no LLM call.
- **JSON as intermediate format** — meal_planner writes `/tmp/meal_plan.json`; writing_agent reads it. Clean separation, easy to debug by inspecting the JSON.
- **Provider-swappable in one file** — `agents/llm.py` contains all provider-specific code. Change `BASE_URL` and `build_headers()` to switch to Anthropic, Gemini, or any OpenAI-compatible API.
- **History over deduplication** — unlike tenkai's URL dedup, we track meal names in a rolling 8-week window. Meals naturally repeat seasonally, so we only avoid the last 8 weeks.
- **Prep optimization is LLM-driven** — the LLM is prompted to identify shared ingredients and assign prep tasks to sessions. No algorithmic scheduling needed; the LLM handles it naturally when given the session constraints.
- **Writing is deterministic** — the writing agent templates from JSON, no LLM involved. This saves quota and produces consistent formatting.
