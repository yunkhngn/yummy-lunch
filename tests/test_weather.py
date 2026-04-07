import httpx
import pytest
import respx

from src.weather import WeatherInfo, fetch_weather


FAKE_RESPONSE = {
    "current": {
        "temperature_2m": 28.5,
        "apparent_temperature": 32.0,
        "relative_humidity_2m": 85,
        "wind_speed_10m": 3.2,
        "weather_code": 61,
    }
}


class TestFetchWeather:
    @respx.mock
    @pytest.mark.asyncio
    async def test_returns_weather_info(self):
        respx.get("https://api.open-meteo.com/v1/forecast").mock(
            return_value=httpx.Response(200, json=FAKE_RESPONSE)
        )

        result = await fetch_weather(lat=10.762, lon=106.682)

        assert isinstance(result, WeatherInfo)
        assert result.condition == "Rain"
        assert result.description == "mưa"
        assert result.temp_c == 28.5
        assert result.feels_like_c == 32.0
        assert result.humidity == 85
        assert result.wind_speed == 3.2
        assert result.city == "10.762,106.682"

    @respx.mock
    @pytest.mark.asyncio
    async def test_api_error_raises(self):
        respx.get("https://api.open-meteo.com/v1/forecast").mock(
            return_value=httpx.Response(500, json={"reason": "internal"})
        )

        with pytest.raises(RuntimeError, match="Weather API error"):
            await fetch_weather(lat=10.762, lon=106.682)

    @respx.mock
    @pytest.mark.asyncio
    async def test_request_params_are_correct(self):
        route = respx.get("https://api.open-meteo.com/v1/forecast").mock(
            return_value=httpx.Response(200, json=FAKE_RESPONSE)
        )

        await fetch_weather(lat=10.762, lon=106.682)

        assert route.called
        request = route.calls[0].request
        assert "latitude=10.762" in str(request.url)
        assert "longitude=106.682" in str(request.url)
        assert "current=" in str(request.url)
