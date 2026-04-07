import os

import pytest
from unittest.mock import patch


def _make_env(**overrides):
    base = {
        "TELEGRAM_BOT_TOKEN": "test-telegram-token",
        "GEMINI_API_KEY": "test-gemini-key",
        "MY_ADDRESS": "227 Nguyễn Văn Cừ, Quận 5, TP.HCM",
        "MY_LATITUDE": "10.7620",
        "MY_LONGITUDE": "106.6822",
        "SEARCH_RADIUS_KM": "2",
    }
    base.update(overrides)
    return base


class TestConfig:
    @patch.dict(os.environ, _make_env(), clear=True)
    def test_loads_all_values(self):
        from src.config import load_config

        cfg = load_config()
        assert cfg.telegram_token == "test-telegram-token"
        assert cfg.gemini_api_key == "test-gemini-key"
        assert cfg.address == "227 Nguyễn Văn Cừ, Quận 5, TP.HCM"
        assert cfg.latitude == 10.7620
        assert cfg.longitude == 106.6822
        assert cfg.search_radius_km == 2

    @patch("src.config.load_dotenv", return_value=None)
    @patch.dict(os.environ, {}, clear=True)
    def test_missing_required_var_raises(self, _mock_load_dotenv):
        from src.config import load_config

        with pytest.raises(ValueError, match="TELEGRAM_BOT_TOKEN"):
            load_config()

    @patch.dict(os.environ, _make_env(SEARCH_RADIUS_KM="5"), clear=True)
    def test_radius_clamped_to_max_3(self):
        from src.config import load_config

        cfg = load_config()
        assert cfg.search_radius_km == 3

    @patch.dict(os.environ, _make_env(SEARCH_RADIUS_KM="0"), clear=True)
    def test_radius_clamped_to_min_1(self):
        from src.config import load_config

        cfg = load_config()
        assert cfg.search_radius_km == 1
