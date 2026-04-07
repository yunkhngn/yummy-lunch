import json
from datetime import date
from unittest.mock import patch

import pytest

from src.history import (
    clear_history,
    get_past_suggestions,
    load_history,
    save_entry,
)


@pytest.fixture
def tmp_history(tmp_path):
    return tmp_path / "history.json"


class TestLoadHistory:
    def test_returns_empty_when_no_file(self, tmp_history):
        result = load_history(tmp_history)
        assert result.week == ""
        assert result.entries == []

    def test_loads_existing_file(self, tmp_history):
        data = {
            "week": "2026-W15",
            "entries": [
                {
                    "date": "2026-04-06",
                    "weekday": "Thứ Hai",
                    "meal": "bữa trưa",
                    "suggestion": "Phở bò",
                }
            ],
        }
        tmp_history.write_text(json.dumps(data), encoding="utf-8")

        result = load_history(tmp_history)
        assert result.week == "2026-W15"
        assert len(result.entries) == 1
        assert result.entries[0]["suggestion"] == "Phở bò"

    @patch("src.history._current_iso_week", return_value="2026-W16")
    def test_auto_resets_when_week_changes(self, _mock_week, tmp_history):
        old_data = {
            "week": "2026-W15",
            "entries": [
                {
                    "date": "2026-04-06",
                    "weekday": "Thứ Hai",
                    "meal": "bữa trưa",
                    "suggestion": "Phở bò",
                }
            ],
        }
        tmp_history.write_text(json.dumps(old_data), encoding="utf-8")

        result = load_history(tmp_history)
        assert result.week == "2026-W16"
        assert result.entries == []


class TestSaveEntry:
    @patch("src.history._current_iso_week", return_value="2026-W15")
    @patch("src.history._today", return_value=date(2026, 4, 7))
    def test_saves_new_entry(self, _mock_today, _mock_week, tmp_history):
        save_entry(
            filepath=tmp_history,
            meal="bữa trưa",
            suggestion="Ăn bún bò Huế nhé!",
        )

        data = json.loads(tmp_history.read_text(encoding="utf-8"))
        assert data["week"] == "2026-W15"
        assert len(data["entries"]) == 1
        assert data["entries"][0]["date"] == "2026-04-07"
        assert data["entries"][0]["weekday"] == "Thứ Ba"
        assert data["entries"][0]["meal"] == "bữa trưa"
        assert data["entries"][0]["suggestion"] == "Ăn bún bò Huế nhé!"

    @patch("src.history._current_iso_week", return_value="2026-W15")
    @patch("src.history._today", return_value=date(2026, 4, 8))
    def test_appends_to_existing(self, _mock_today, _mock_week, tmp_history):
        existing = {
            "week": "2026-W15",
            "entries": [
                {
                    "date": "2026-04-07",
                    "weekday": "Thứ Ba",
                    "meal": "bữa trưa",
                    "suggestion": "Phở bò",
                }
            ],
        }
        tmp_history.write_text(json.dumps(existing), encoding="utf-8")

        save_entry(
            filepath=tmp_history,
            meal="bữa tối",
            suggestion="Cơm tấm sườn bì chả",
        )

        data = json.loads(tmp_history.read_text(encoding="utf-8"))
        assert len(data["entries"]) == 2

    @patch("src.history._current_iso_week", return_value="2026-W15")
    @patch("src.history._today", return_value=date(2026, 4, 11))
    def test_skips_save_on_weekend(self, _mock_today, _mock_week, tmp_history):
        save_entry(
            filepath=tmp_history,
            meal="bữa trưa",
            suggestion="Phở bò",
        )

        assert not tmp_history.exists()


class TestGetPastSuggestions:
    def test_returns_formatted_past(self, tmp_history):
        data = {
            "week": "2026-W15",
            "entries": [
                {
                    "date": "2026-04-06",
                    "weekday": "Thứ Hai",
                    "meal": "bữa trưa",
                    "suggestion": "Phở bò tái nạm",
                },
                {
                    "date": "2026-04-07",
                    "weekday": "Thứ Ba",
                    "meal": "bữa tối",
                    "suggestion": "Cơm tấm sườn bì",
                },
            ],
        }
        tmp_history.write_text(json.dumps(data), encoding="utf-8")

        result = get_past_suggestions(tmp_history)
        assert "Thứ Hai" in result
        assert "Phở bò tái nạm" in result
        assert "Thứ Ba" in result
        assert "Cơm tấm sườn bì" in result
        assert "**" not in result

    def test_returns_empty_string_when_no_history(self, tmp_history):
        result = get_past_suggestions(tmp_history)
        assert result == ""


class TestClearHistory:
    def test_clears_file(self, tmp_history):
        data = {"week": "2026-W15", "entries": [{"suggestion": "test"}]}
        tmp_history.write_text(json.dumps(data), encoding="utf-8")

        clear_history(tmp_history)

        assert not tmp_history.exists()
