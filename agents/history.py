"""History tracking for meal plans — rolling 8-week window."""

import json
from pathlib import Path

HISTORY_PATH = Path(__file__).parent / "history.json"
MAX_WEEKS = 8


def load_history(path: Path = HISTORY_PATH) -> list[dict]:
    if not path.exists():
        return []
    return json.loads(path.read_text()).get("meals", [])


def save_history(week_of: str, meal_names: list[str], path: Path = HISTORY_PATH) -> None:
    history = load_history(path)
    history.insert(0, {"week_of": week_of, "names": meal_names})
    history = history[:MAX_WEEKS]
    path.write_text(json.dumps({"meals": history}, indent=2))


def recent_meal_names(history: list[dict], weeks: int = MAX_WEEKS) -> list[str]:
    names = []
    for entry in history[:weeks]:
        names.extend(entry.get("names", []))
    return names
