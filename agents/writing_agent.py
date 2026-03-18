"""Formats /tmp/meal_plan.json into a Hugo markdown post."""

import json
import sys
from datetime import datetime
from pathlib import Path

INPUT_PATH = Path("/tmp/meal_plan.json")
POSTS_DIR = Path(__file__).parent.parent / "content" / "posts"

GROCERY_CATEGORIES = {
    "produce": [
        "pepper", "onion", "garlic", "tomato", "lettuce", "spinach", "kale", "zucchini",
        "carrot", "celery", "cucumber", "broccoli", "cauliflower", "mushroom", "potato",
        "sweet potato", "corn", "pea", "bean", "lemon", "lime", "avocado", "eggplant",
        "squash", "herb", "basil", "cilantro", "parsley", "ginger", "scallion", "leek",
        "asparagus", "cabbage", "arugula", "apple", "banana", "mango",
    ],
    "proteins": [
        "chicken", "beef", "pork", "lamb", "tofu", "tempeh", "fish", "salmon", "tuna",
        "shrimp", "egg", "lentil", "chickpea", "black bean", "kidney bean", "edamame",
        "turkey", "sausage", "bacon", "seitan",
    ],
    "pantry": [],  # catch-all
}


def categorize_item(item: str) -> str:
    item_lower = item.lower()
    for category, keywords in GROCERY_CATEGORIES.items():
        if category == "pantry":
            continue
        if any(kw in item_lower for kw in keywords):
            return category
    return "pantry"


def format_date_long(iso_date: str) -> str:
    return datetime.strptime(iso_date, "%Y-%m-%d").strftime("%B %-d, %Y")


def render_front_matter(meal_plan: dict) -> str:
    week_of = meal_plan["week_of"]
    meals = meal_plan.get("meals", [])
    meal_names = [m["name"] for m in meals[:3]]
    names_preview = ", ".join(meal_names)
    if len(meals) > 3:
        names_preview += f", and {len(meals) - 3} more"

    prep_tasks_total = sum(len(s.get("tasks", [])) for s in meal_plan.get("prep_sessions", []))
    date_long = format_date_long(week_of)

    return f"""\
---
title: "Meal Plan — Week of {date_long}"
date: {week_of}
draft: false
tags: [meal-plan, weekly]
description: "7 dinners: {names_preview}. {prep_tasks_total} prep tasks across 2 sessions."
---
"""


def render_overview_table(meals: list[dict]) -> str:
    lines = [
        "## This Week's Meals\n",
        "| Day | Meal | Active Time |",
        "|-----|------|-------------|",
    ]
    for meal in meals:
        day = meal["day"]
        name = meal["name"]
        active = meal.get("time_active_minutes", "—")
        lines.append(f"| {day} | {name} | {active} min |")
    return "\n".join(lines) + "\n"


def render_recipes(meals: list[dict]) -> str:
    sections = ["## Recipes\n"]
    for meal in meals:
        sections.append(f"### {meal['day']}: {meal['name']}\n")
        sections.append(f"**Serves:** {meal.get('serves', '—')}  ")
        sections.append(
            f"**Active:** {meal.get('time_active_minutes', '—')} min  "
            f"**Total:** {meal.get('time_total_minutes', '—')} min\n"
        )

        sections.append("**Ingredients:**\n")
        for ing in meal.get("ingredients", []):
            amount = ing.get("amount", "")
            unit = ing.get("unit", "")
            qty = f"{amount} {unit}".strip()
            sections.append(f"- {ing['item']}: {qty}")

        sections.append("\n**Steps:**\n")
        for i, step in enumerate(meal.get("recipe_steps", []), 1):
            sections.append(f"{i}. {step}")

        variations = meal.get("variations", {})
        if variations:
            sections.append("\n> **Variations:**")
            for person, note in variations.items():
                sections.append(f"> - **{person}:** {note}")

        sections.append("")
    return "\n".join(sections) + "\n"


def render_prep_plan(prep_sessions: list[dict]) -> str:
    lines = ["## Meal Prep Plan\n"]
    for session in prep_sessions:
        label = session.get("label", "Prep")
        day = session.get("day", "")
        lines.append(f"### {label} ({day})\n")
        for task in session.get("tasks", []):
            lines.append(f"- {task}")
        lines.append("")
    return "\n".join(lines) + "\n"


def render_grocery_list(grocery_list: list[dict]) -> str:
    categorized: dict[str, list[dict]] = {"produce": [], "proteins": [], "pantry": []}
    for item in grocery_list:
        cat = categorize_item(item["item"])
        categorized[cat].append(item)

    lines = ["## Grocery List\n"]
    for category, items in categorized.items():
        if not items:
            continue
        lines.append(f"### {category.capitalize()}\n")
        for item in items:
            used_in = ", ".join(item.get("used_in", []))
            lines.append(f"- **{item['item']}** — {item['total_amount']} *(used: {used_in})*")
        lines.append("")
    return "\n".join(lines)


def main() -> None:
    meal_plan = json.loads(INPUT_PATH.read_text())
    week_of = meal_plan["week_of"]

    POSTS_DIR.mkdir(parents=True, exist_ok=True)
    output_path = POSTS_DIR / f"{week_of}.md"

    post = "\n".join([
        render_front_matter(meal_plan),
        render_overview_table(meal_plan.get("meals", [])),
        render_recipes(meal_plan.get("meals", [])),
        render_prep_plan(meal_plan.get("prep_sessions", [])),
        render_grocery_list(meal_plan.get("grocery_list", [])),
    ])

    output_path.write_text(post)
    print(f"Hugo post written to {output_path}", file=sys.stderr)


if __name__ == "__main__":
    main()
