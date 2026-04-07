import httpx
import pytest
import respx

from src.weather import WeatherInfo, fetch_weather


FAKE_RESPONSE = {
    "weather": [{"main": "Rain", "description": "mưa nhẹ"}],
    "main": {"temp": 28.5, "feels_like": 32.0, "humidity": 85},
    "wind": {"speed": 3.2},
    "name": "Ho Chi Minh City",
}


class TestFetchWeather:
    @respx.mock
    @pytest.mark.asyncio
    async def test_returns_weather_info(self):
        respx.get("https://api.openweathermap.org/data/2.5/weather").mock(
            return_value=httpx.Response(200, json=FAKE_RESPONSE)
        )

        result = await fetch_weather(
            api_key="fake-key", lat=10.762, lon=106.682
        )

        assert isinstance(result, WeatherInfo)
        assert result.condition == "Rain"
        assert result.description == "mưa nhẹ"
        assert result.temp_c == 28.5
        assert result.feels_like_c == 32.0
        assert result.humidity == 85
        assert result.wind_speed == 3.2
        assert result.city == "Ho Chi Minh City"

    @respx.mock
    @pytest.mark.asyncio
    async def test_api_error_raises(self):
        respx.get("https://api.openweathermap.org/data/2.5/weather").mock(
            return_value=httpx.Response(401, json={"message": "Invalid API key"})
        )

        with pytest.raises(RuntimeError, match="Weather API error"):
            await fetch_weather(api_key="bad-key", lat=10.762, lon=106.682)

    @respx.mock
    @pytest.mark.asyncio
    async def test_request_params_are_correct(self):
        route = respx.get("https://api.openweathermap.org/data/2.5/weather").mock(
            return_value=httpx.Response(200, json=FAKE_RESPONSE)
        )

        await fetch_weather(api_key="my-key", lat=10.762, lon=106.682)

        assert route.called
        request = route.calls[0].request
        assert "lat=10.762" in str(request.url)
        assert "lon=106.682" in str(request.url)
        assert "units=metric" in str(request.url)
        assert "lang=vi" in str(request.url)
