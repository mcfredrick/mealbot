"""Generates a weekly meal plan JSON using an LLM."""

import json
import os
import sys
from datetime import date, timedelta
from pathlib import Path

import yaml

from history import load_history, recent_meal_names, save_history
from llm import call_llm

CONFIG_PATH = Path(__file__).parent.parent / "config" / "family.yaml"
OUTPUT_PATH = Path("/tmp/meal_plan.json")

SYSTEM_PROMPT = """\
You are a meal planning assistant. Generate a 7-dinner meal plan for a family.

Rules:
- Every meal must be safe for ALL family members (respect all hard restrictions absolutely)
- Where family members have conflicting preferences, design one base recipe with simple variations noted per person
- Coordinate ingredients across meals: if multiple recipes use the same ingredient, note it so prep can be batched
- Prefer seasonal, whole-food ingredients
- Recipes should be realistic weeknight dinners: active cooking time ≤ 45 minutes after prep work is done
- Do not repeat any meal from the recent history provided

Output ONLY valid JSON matching the schema provided. No commentary, no markdown fences.\
"""

JSON_SCHEMA = """\
{
  "week_of": "YYYY-MM-DD",
  "meals": [
    {
      "day": "Monday",
      "name": "Meal Name",
      "serves": 3,
      "time_active_minutes": 20,
      "time_total_minutes": 30,
      "ingredients": [
        {"item": "ingredient name", "amount": "3", "unit": "whole"}
      ],
      "recipe_steps": [
        "Step 1.",
        "Step 2."
      ],
      "variations": {
        "PersonName": "Variation note."
      }
    }
  ],
  "prep_sessions": [
    {
      "label": "Weekend Prep",
      "day": "Sunday",
      "tasks": [
        "Task description."
      ]
    }
  ],
  "grocery_list": [
    {"item": "ingredient name", "total_amount": "quantity + unit", "used_in": ["Monday", "Wednesday"]}
  ]
}\
"""


def next_sunday() -> str:
    today = date.today()
    days_until_sunday = (6 - today.weekday()) % 7
    if days_until_sunday == 0:
        days_until_sunday = 7
    return (today + timedelta(days=days_until_sunday)).isoformat()


def build_user_prompt(config: dict, history: list[dict], week_of: str) -> str:
    family = config.get("family", [])
    prep_sessions = config.get("prep_sessions", [])
    recent = recent_meal_names(history)

    lines = [f"Week of: {week_of}\n", "Family:"]
    for member in family:
        restrictions = ", ".join(member.get("restrictions", [])) or "none"
        preferences = ", ".join(member.get("preferences", [])) or "none"
        lines.append(f"- {member['name']}: restrictions: {restrictions}. Likes: {preferences}.")

    lines.append("\nPrep sessions:")
    for session in prep_sessions:
        lines.append(f"- {session['day']} ({session['label']}): up to {session['max_hours']} hours")

    if recent:
        lines.append("\nRecent meals to avoid repeating:")
        for entry in history[:8]:
            names_str = ", ".join(entry["names"])
            lines.append(f"- Week of {entry['week_of']}: {names_str}")
    else:
        lines.append("\nNo recent meal history.")

    lines.append(f"\nOutput JSON matching this schema exactly:\n{JSON_SCHEMA}")
    return "\n".join(lines)


def extract_json(text: str) -> dict:
    # Strip markdown fences if the LLM added them anyway
    text = text.strip()
    if text.startswith("```"):
        text = text.split("\n", 1)[1]
        text = text.rsplit("```", 1)[0]
    return json.loads(text.strip())


def main() -> None:
    config = yaml.safe_load(CONFIG_PATH.read_text())
    history = load_history()
    week_of = next_sunday()

    preferred_model = os.environ.get("PLANNING_MODEL", "meta-llama/llama-3.3-70b-instruct:free")
    user_prompt = build_user_prompt(config, history, week_of)

    print(f"Generating meal plan for week of {week_of}...", file=sys.stderr)
    raw = call_llm(SYSTEM_PROMPT, user_prompt, preferred_model, max_tokens=4000)

    meal_plan = extract_json(raw)
    meal_plan["week_of"] = week_of  # Ensure week_of is always correct

    OUTPUT_PATH.write_text(json.dumps(meal_plan, indent=2))
    print(f"Meal plan written to {OUTPUT_PATH}", file=sys.stderr)

    meal_names = [m["name"] for m in meal_plan.get("meals", [])]
    save_history(week_of, meal_names)
    print(f"History updated with {len(meal_names)} meals.", file=sys.stderr)


if __name__ == "__main__":
    main()
