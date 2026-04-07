from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path

_WEEKDAY_NAMES = [
    "Thứ Hai",
    "Thứ Ba",
    "Thứ Tư",
    "Thứ Năm",
    "Thứ Sáu",
    "Thứ Bảy",
    "Chủ Nhật",
]


def _current_iso_week() -> str:
    today = date.today()
    year, week, _ = today.isocalendar()
    return f"{year}-W{week:02d}"


def _today() -> date:
    return date.today()


@dataclass
class WeeklyHistory:
    week: str = ""
    entries: list[dict] = field(default_factory=list)


def load_history(filepath: Path) -> WeeklyHistory:
    if not filepath.exists():
        return WeeklyHistory()

    try:
        data = json.loads(filepath.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, KeyError, TypeError):
        return WeeklyHistory()

    current_week = _current_iso_week()
    if data.get("week") != current_week:
        return WeeklyHistory(week=current_week, entries=[])

    return WeeklyHistory(
        week=data["week"],
        entries=data.get("entries", []),
    )


def save_entry(
    *,
    filepath: Path,
    meal: str,
    suggestion: str,
) -> None:
    today = _today()
    weekday_idx = today.weekday()

    if weekday_idx >= 5:
        return

    history = load_history(filepath)
    if not history.week:
        history.week = _current_iso_week()

    history.entries.append(
        {
            "date": today.isoformat(),
            "weekday": _WEEKDAY_NAMES[weekday_idx],
            "meal": meal,
            "suggestion": suggestion,
        }
    )

    filepath.parent.mkdir(parents=True, exist_ok=True)
    filepath.write_text(
        json.dumps(
            {"week": history.week, "entries": history.entries},
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )


def get_past_suggestions(filepath: Path) -> str:
    history = load_history(filepath)
    if not history.entries:
        return ""

    lines = []
    for entry in history.entries:
        lines.append(
            f"- {entry['weekday']} ({entry['meal']}): {entry['suggestion']}"
        )
    return "\n".join(lines)


def clear_history(filepath: Path) -> None:
    if filepath.exists():
        filepath.unlink()
