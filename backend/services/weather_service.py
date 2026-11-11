import logging
import re
import time
from typing import Any, Dict, Optional, Tuple

import requests

logger = logging.getLogger(__name__)

OPEN_METEO_URL = "https://api.open-meteo.com/v1/forecast"
WEATHER_CACHE_TTL_SECONDS = 300  # 5분 캐시

FALLBACK_WEATHER: Dict[str, Any] = {
    "weather": "흐림",
    "icon": "☁️",
    "temp": "10℃",
    "temp_c": 10.0,
    "weather_code": 3,
    "windspeed": 0.0,
    "is_cold": True,
    "is_rainy": False,
    "is_snowy": False,
    "is_hot": False,
}

_WEATHER_CACHE: Dict[Tuple[float, float], Tuple[float, Dict[str, Any]]] = {}


def interpret_wmo_weather_code(weather_code: int) -> Tuple[str, str, bool, bool]:
    """
    Open-Meteo WMO 기상 코드(0~99)를 (이모지 아이콘, 짧은 한글 날씨, 비 여부, 눈 여부)로 변환합니다.
    """
    try:
        code = int(weather_code)
    except (TypeError, ValueError):
        return ("☁️", "흐림", False, False)

    if code == 0:
        return ("☀️", "맑음", False, False)
    if code == 1:
        return ("🌤️", "맑음", False, False)
    if code == 2:
        return ("⛅", "구름 조금", False, False)
    if code == 3:
        return ("☁️", "흐림", False, False)
    if code in (45, 48):
        return ("🌫️", "안개", False, False)
    if code in (51, 53, 55, 56, 57):
        return ("🌦️", "이슬비", True, False)
    if code in (61, 63, 65, 66, 67, 80, 81, 82):
        return ("🌧️", "비", True, False)
    if code in (71, 73, 75, 77, 85, 86):
        return ("🌨️", "눈", False, True)
    if code in (95, 96, 99):
        return ("⛈️", "천둥번개", True, False)
    return ("☁️", "흐림", False, False)


def infer_weather_icon(weather_text: str) -> str:
    """날씨 설명 문자열에서 미니멀 기상 아이콘 이모지를 추론합니다."""
    text = str(weather_text or "").strip()
    if any(k in text for k in ("번개", "뇌우", "천둥")):
        return "⛈️"
    if any(k in text for k in ("이슬비", "가랑비")):
        return "🌦️"
    if any(k in text for k in ("비", "소나기", "강수", "우천")):
        return "🌧️"
    if any(k in text for k in ("눈", "진눈깨비", "함박눈")):
        return "🌨️"
    if any(k in text for k in ("안개", "박무", "연무")):
        return "🌫️"
    if "구름" in text:
        return "⛅"
    if "흐림" in text:
        return "☁️"
    if "맑" in text:
        return "☀️"
    return "🌤️"


def _parse_temp_c(temp_text: Optional[str], default: float = 10.0) -> float:
    if temp_text is None:
        return default
    match = re.search(r"-?\d+(?:\.\d+)?", str(temp_text))
    if not match:
        return default
    try:
        return float(match.group(0))
    except ValueError:
        return default


def get_current_weather(lat: float, lon: float) -> Dict[str, Any]:
    """
    무료·키 프리 Open-Meteo API로 위도/경도 기준 실시간 날씨를 조회합니다.
    (엔드포인트: https://api.open-meteo.com/v1/forecast?latitude={lat}&longitude={lon}&current_weather=true)
    """
    cache_key = (round(float(lat), 2), round(float(lon), 2))
    now = time.time()
    cached = _WEATHER_CACHE.get(cache_key)
    if cached and (now - cached[0]) < WEATHER_CACHE_TTL_SECONDS:
        return dict(cached[1])

    params = {
        "latitude": float(lat),
        "longitude": float(lon),
        "current_weather": "true",
    }

    try:
        response = requests.get(OPEN_METEO_URL, params=params, timeout=4)
        response.raise_for_status()
        data = response.json()
        current = data.get("current_weather") or {}
        if not current:
            raise ValueError("current_weather payload missing")

        temp_c = float(current.get("temperature", 10.0))
        weather_code = int(current.get("weathercode", 3))
        windspeed = float(current.get("windspeed", 0.0))
        icon, desc, is_rainy, is_snowy = interpret_wmo_weather_code(weather_code)

        result: Dict[str, Any] = {
            "weather": desc,
            "icon": icon,
            "temp": f"{round(temp_c)}℃",
            "temp_c": round(temp_c, 1),
            "weather_code": weather_code,
            "windspeed": round(windspeed, 1),
            "is_cold": temp_c <= 12.0,
            "is_rainy": is_rainy,
            "is_snowy": is_snowy,
            "is_hot": temp_c >= 26.0,
        }
        _WEATHER_CACHE[cache_key] = (now, result)
        return dict(result)
    except Exception as exc:
        logger.warning("Open-Meteo 날씨 조회 실패(%s)로 인해 폴백 날씨를 반환합니다.", exc)
        return dict(FALLBACK_WEATHER)


def merge_weather_context(
    lat: float,
    lon: float,
    client_weather: Optional[str] = None,
    client_temp: Optional[str] = None,
    client_icon: Optional[str] = None,
) -> Dict[str, Any]:
    """
    프론트엔드가 전달한 Open-Meteo 현재 날씨 상태(기온, 날씨)가 있으면 우선 반영하고,
    누락 시 백엔드에서 직접 Open-Meteo API를 조회해 AI 판단용 날씨 플래그를 완성합니다.
    """
    clean_weather = str(client_weather or "").strip()
    clean_temp = str(client_temp or "").strip()
    clean_icon = str(client_icon or "").strip()

    if clean_weather and clean_temp:
        temp_c = _parse_temp_c(clean_temp, default=10.0)
        icon = clean_icon or infer_weather_icon(clean_weather)
        is_rainy = any(k in clean_weather for k in ("비", "소나기", "강수", "우천", "이슬비", "천둥", "번개"))
        is_snowy = any(k in clean_weather for k in ("눈", "진눈깨비"))
        normalized_temp = clean_temp if ("℃" in clean_temp or "°" in clean_temp) else f"{round(temp_c)}℃"
        return {
            "weather": clean_weather,
            "icon": icon,
            "temp": normalized_temp,
            "temp_c": round(temp_c, 1),
            "weather_code": None,
            "windspeed": 0.0,
            "is_cold": temp_c <= 12.0,
            "is_rainy": is_rainy,
            "is_snowy": is_snowy,
            "is_hot": temp_c >= 26.0,
        }

    live = get_current_weather(lat, lon)
    if clean_weather:
        live["weather"] = clean_weather
        live["icon"] = clean_icon or infer_weather_icon(clean_weather)
        live["is_rainy"] = any(k in clean_weather for k in ("비", "소나기", "강수", "우천", "이슬비", "천둥", "번개"))
        live["is_snowy"] = any(k in clean_weather for k in ("눈", "진눈깨비"))
    if clean_temp:
        temp_c = _parse_temp_c(clean_temp, default=float(live.get("temp_c", 10.0)))
        live["temp"] = clean_temp if ("℃" in clean_temp or "°" in clean_temp) else f"{round(temp_c)}℃"
        live["temp_c"] = round(temp_c, 1)
        live["is_cold"] = temp_c <= 12.0
        live["is_hot"] = temp_c >= 26.0
    return live
