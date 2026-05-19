from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.suggest import build_prompt, build_thank_you_prompt, get_suggestion
from src.weather import WeatherInfo


class TestBuildThankYouPrompt:
    def test_contains_boss_name(self):
        prompt = build_thank_you_prompt("Anh Nam")
        assert "Anh Nam" in prompt

    def test_requests_three_paragraphs(self):
        prompt = build_thank_you_prompt("Chị Lan")
        assert "3 đoạn văn" in prompt

    def test_no_emoji_instruction(self):
        prompt = build_thank_you_prompt("Sếp")
        assert "KHÔNG dùng emoji" in prompt

    def test_vietnamese_instruction(self):
        prompt = build_thank_you_prompt("Anh Tuấn")
        assert "tiếng Việt có dấu" in prompt


def _sample_weather() -> WeatherInfo:
    return WeatherInfo(
        condition="Rain",
        description="mưa nhẹ",
        temp_c=28.5,
        feels_like_c=32.0,
        humidity=85,
        wind_speed=3.2,
        city="Ho Chi Minh City",
    )


class TestBuildPrompt:
    def _default_prompt(self, **overrides):
        kwargs = dict(
            weather=_sample_weather(),
            address="227 Nguyễn Văn Cừ, Q5",
            latitude=10.762,
            longitude=106.682,
            radius_km=2,
            meal_period="bữa trưa",
            past_suggestions="",
        )
        kwargs.update(overrides)
        return build_prompt(**kwargs)

    def test_contains_context(self):
        prompt = self._default_prompt()
        assert "28.5" in prompt
        assert "227 Nguyễn Văn Cừ, Q5" in prompt
        assert "2 km" in prompt

    def test_enforces_single_dish(self):
        prompt = self._default_prompt()
        assert "một món ăn duy nhất" in prompt

    def test_vietnamese_diacritics_instruction(self):
        prompt = self._default_prompt()
        assert "tiếng Việt có dấu" in prompt

    def test_no_emoji_instruction(self):
        prompt = self._default_prompt()
        assert "KHÔNG" in prompt
        assert "emoji" in prompt.lower()

    def test_no_history_section_when_empty(self):
        prompt = self._default_prompt()
        assert "Đã gợi ý trong tuần" not in prompt

    def test_includes_history_when_provided(self):
        past = (
            "- Thứ Hai (bữa trưa): Phở bò tái nạm\n"
            "- Thứ Ba (bữa tối): Cơm tấm"
        )
        prompt = self._default_prompt(
            meal_period="bữa tối",
            past_suggestions=past,
        )
        assert "Đã gợi ý trong tuần" in prompt
        assert "Phở bò tái nạm" in prompt
        assert "Cơm tấm" in prompt
        assert "KHÔNG" in prompt

    def test_contains_google_maps_instructions(self):
        prompt = self._default_prompt()
        assert "google.com/maps/dir" in prompt
        assert "10.762" in prompt
        assert "106.682" in prompt
        assert "walking" in prompt
        assert "two-wheeler" in prompt

    def test_budget_and_group_size(self):
        prompt = self._default_prompt()
        assert "50.000" in prompt
        assert "5–6" in prompt or "5-6" in prompt


class TestGetSuggestion:
    @pytest.mark.asyncio
    @patch("src.suggest.genai")
    async def test_calls_gemini_and_returns_text(self, mock_genai):
        mock_response = MagicMock()
        mock_response.text = (
            "Món: Phở bò\n"
            "Quán: Phở Hòa Pasteur — 260C Pasteur, Q3\n"
            "Giá: khoảng 45.000 đồng/người\n"
            "Cách khoảng: 1,5 km\n"
            "Lý do: Trời mưa, phở nóng rất hợp."
        )

        mock_client = MagicMock()
        mock_client.aio.models.generate_content = AsyncMock(
            return_value=mock_response
        )
        mock_genai.Client.return_value = mock_client

        result = await get_suggestion(
            api_key="fake-key",
            weather=_sample_weather(),
            address="227 Nguyễn Văn Cừ, Q5",
            latitude=10.762,
            longitude=106.682,
            radius_km=2,
            meal_period="bữa trưa",
            past_suggestions="",
        )

        assert "Phở bò" in result.text
        assert "Phở Hòa Pasteur" in result.text
        assert result.matched_place is None
        mock_client.aio.models.generate_content.assert_called_once()

