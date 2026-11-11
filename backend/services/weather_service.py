import logging
import os
from pathlib import Path
from typing import Any, Dict

import requests
from dotenv import load_dotenv

load_dotenv(Path(__file__).resolve().parents[2] / ".env")

logger = logging.getLogger(__name__)

OPENWEATHER_CURRENT_URL = "https://api.openweathermap.org/data/2.5/weather"
FALLBACK_WEATHER: Dict[str, Any] = {
    "weather": "쌀쌀한 흐림",
    "temp": "7℃",
    "is_cold": True,
}


def get_current_weather(lat: float, lon: float) -> Dict[str, Any]:
    """OpenWeatherMap API로 현재 날씨를 조회하고, 키가 없거나 실패 시 늦가을/초겨울 폴백 날씨를 반환합니다."""
    api_key = os.getenv("OPENWEATHER_API_KEY", "").strip()
    if not api_key:
        return dict(FALLBACK_WEATHER)

    params = {
        "lat": lat,
        "lon": lon,
        "appid": api_key,
        "units": "metric",
        "lang": "kr",
    }

    try:
        response = requests.get(OPENWEATHER_CURRENT_URL, params=params, timeout=4)
        response.raise_for_status()
        data = response.json()

        weather_list = data.get("weather", [])
        description = (
            weather_list[0].get("description", "쌀쌀한 흐림")
            if weather_list
            else "쌀쌀한 흐림"
        )
        temp_c = float(data.get("main", {}).get("temp", 7.0))
        return {
            "weather": description,
            "temp": f"{round(temp_c)}℃",
            "is_cold": temp_c <= 12.0,
        }
    except Exception as exc:
        logger.warning("OpenWeather API 호출 실패(%s)로 인해 폴백 날씨를 반환합니다.", exc)
        return dict(FALLBACK_WEATHER)
