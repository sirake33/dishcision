import logging
import os
from pathlib import Path
from typing import Any, Dict, List
from urllib.parse import quote

import requests
from dotenv import load_dotenv

load_dotenv(Path(__file__).resolve().parents[2] / ".env")

logger = logging.getLogger(__name__)

KAKAO_LOCAL_CATEGORY_URL = "https://dapi.kakao.com/v2/local/search/category.json"


def _meters_to_walk_time(distance_str: str) -> str:
    """거리(m) 문자열을 도보 시간 문자열(예: '도보 4분')로 변환합니다."""
    try:
        meters = int(distance_str)
    except (TypeError, ValueError):
        return "도보 5분"
    minutes = max(1, round(meters / 67))
    return f"도보 {minutes}분"


def get_fallback_restaurants() -> List[Dict[str, Any]]:
    """카카오 API 실패 또는 결과 없음 시 시연이 중단되지 않도록 협성대/봉담 주변 목업 데이터를 반환합니다."""
    fallback_items = [
        {
            "place_name": "맘스터치 협성대점",
            "category_name": "음식점 > 패스트푸드 > 햄버거",
            "distance": "240",
            "distance_walk": "도보 4분",
            "road_address_name": "경기도 화성시 봉담읍 최루백로 72",
            "place_url": f"https://map.kakao.com/link/search/{quote('맘스터치 협성대점')}",
            "phone": "031-297-0001",
            "menu_hints": "싸이버거 단품 4,900원 / 싸이버거 세트 7,300원 / 딥치즈버거 세트 7,800원",
        },
        {
            "place_name": "이삭토스트 봉담점",
            "category_name": "음식점 > 간식 > 토스트",
            "distance": "320",
            "distance_walk": "도보 5분",
            "road_address_name": "경기도 화성시 봉담읍 삼천병마로 1205",
            "place_url": f"https://map.kakao.com/link/search/{quote('이삭토스트 봉담점')}",
            "phone": "031-297-0002",
            "menu_hints": "햄치즈 토스트 3,600원 / 햄치즈 스페셜 3,900원 / 베이컨 포테이토 피자 토스트 5,200원",
        },
        {
            "place_name": "봉구스밥버거 화성봉담점",
            "category_name": "음식점 > 분식 > 밥버거",
            "distance": "210",
            "distance_walk": "도보 3분",
            "road_address_name": "경기도 화성시 봉담읍 최루백로 68",
            "place_url": f"https://map.kakao.com/link/search/{quote('봉구스밥버거 화성봉담점')}",
            "phone": "031-297-0003",
            "menu_hints": "봉구스밥버거 3,500원 / 제육밥버거 4,500원 / 치즈닭갈비 밥버거 5,000원",
        },
        {
            "place_name": "담소소사골순대육개장",
            "category_name": "음식점 > 한식 > 국밥/순대국",
            "distance": "480",
            "distance_walk": "도보 7분",
            "road_address_name": "경기도 화성시 봉담읍 상리 1길 15",
            "place_url": f"https://map.kakao.com/link/search/{quote('담소소사골순대육개장')}",
            "phone": "031-297-0004",
            "menu_hints": "우사골 순대국 8,500원 / 돈사골 순대국 7,900원 / 소사골 육개장 9,000원",
        },
        {
            "place_name": "샐러디 봉담점",
            "category_name": "음식점 > 양식 > 샐러드/포케",
            "distance": "410",
            "distance_walk": "도보 6분",
            "road_address_name": "경기도 화성시 봉담읍 삼천병마로 1190",
            "place_url": f"https://map.kakao.com/link/search/{quote('샐러디 봉담점')}",
            "phone": "031-297-0005",
            "menu_hints": "우삼겹 웜볼 8,900원 / 칠리베이컨 웜볼 7,900원 / 멕시칸 랩 샌드위치 7,500원",
        },
        {
            "place_name": "한솥도시락 협성대점",
            "category_name": "음식점 > 한식 > 도시락",
            "distance": "180",
            "distance_walk": "도보 3분",
            "road_address_name": "경기도 화성시 봉담읍 최루백로 75",
            "place_url": f"https://map.kakao.com/link/search/{quote('한솥도시락 협성대점')}",
            "phone": "031-297-0006",
            "menu_hints": "치킨마요 4,300원 / 돈까스 도련님 4,900원 / 빅치킨마요 4,900원",
        },
        {
            "place_name": "홍콩반점0410 봉담점",
            "category_name": "음식점 > 중식 > 짬뽕/짜장",
            "distance": "520",
            "distance_walk": "도보 8분",
            "road_address_name": "경기도 화성시 봉담읍 상리 2길 21",
            "place_url": f"https://map.kakao.com/link/search/{quote('홍콩반점0410 봉담점')}",
            "phone": "031-297-0007",
            "menu_hints": "짬뽕 7,500원 / 짜장면 6,500원 / 짬뽕밥 8,000원",
        },
    ]
    return fallback_items


def get_nearby_restaurants(
    lat: float, lon: float, radius: int = 1000
) -> List[Dict[str, Any]]:
    """카카오 로컬 REST API(FD6)로 주변 식당을 조회하고, 실패 또는 빈 결과 시 목업 폴백을 반환합니다."""
    api_key = os.getenv("KAKAO_REST_API_KEY", "").strip()
    if not api_key:
        logger.warning("KAKAO_REST_API_KEY가 설정되지 않아 폴백 식당 목록을 반환합니다.")
        return get_fallback_restaurants()

    headers = {"Authorization": f"KakaoAK {api_key}"}
    params = {
        "category_group_code": "FD6",
        "x": str(lon),
        "y": str(lat),
        "radius": radius,
        "sort": "distance",
        "size": 15,
    }

    try:
        response = requests.get(
            KAKAO_LOCAL_CATEGORY_URL,
            headers=headers,
            params=params,
            timeout=4,
        )
        response.raise_for_status()
        data = response.json()
        documents = data.get("documents", [])

        if not documents:
            logger.warning("카카오 로컬 API 검색 결과가 비어 있어 폴백 식당 목록을 반환합니다.")
            return get_fallback_restaurants()

        restaurants: List[Dict[str, Any]] = []
        for doc in documents:
            place_name = doc.get("place_name", "").strip()
            if not place_name:
                continue
            distance = str(doc.get("distance", "350"))
            place_url = doc.get("place_url") or f"https://map.kakao.com/link/search/{quote(place_name)}"
            restaurants.append(
                {
                    "place_name": place_name,
                    "category_name": doc.get("category_name", "음식점"),
                    "distance": distance,
                    "distance_walk": _meters_to_walk_time(distance),
                    "road_address_name": doc.get("road_address_name") or doc.get("address_name", ""),
                    "place_url": place_url,
                    "phone": doc.get("phone", ""),
                }
            )

        if not restaurants:
            return get_fallback_restaurants()

        return restaurants

    except Exception as exc:
        logger.warning("카카오 로컬 API 호출 실패(%s)로 인해 폴백 식당 목록을 반환합니다.", exc)
        return get_fallback_restaurants()
