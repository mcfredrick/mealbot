# mealbot

An autonomous weekly meal planning blog hosted on GitHub Pages.

Every Sunday, a GitHub Actions workflow uses free OpenRouter LLMs to generate a personalized 7-day meal plan. The output is a [Hugo](https://gohugo.io/) blog post with 7 dinners (with dietary variations), a meal prep plan, and a consolidated grocery list.

## How it works

1. **model_selector** — picks the best free OpenRouter models at runtime
2. **meal_planner** — generates a meal plan as JSON using an LLM
3. **writing_agent** — formats the JSON into a Hugo markdown post
4. Hugo builds the site and deploys to GitHub Pages

## Configuration

Edit `config/family.yaml` to set family members, dietary restrictions, preferences, and prep schedule.

## Requirements

```
pip install -r requirements.txt
```

## Live site

[https://mcfredrick.github.io/mealbot/](https://mcfredrick.github.io/mealbot/)
