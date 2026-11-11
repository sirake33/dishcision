import logging
import math
import os
import re
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple
from urllib.parse import quote

import requests
from dotenv import load_dotenv

load_dotenv(Path(__file__).resolve().parents[2] / ".env")

logger = logging.getLogger(__name__)

KAKAO_LOCAL_CATEGORY_URL = "https://dapi.kakao.com/v2/local/search/category.json"
KAKAO_LOCAL_KEYWORD_URL = "https://dapi.kakao.com/v2/local/search/keyword.json"
KAKAO_LOCAL_ADDRESS_URL = "https://dapi.kakao.com/v2/local/search/address.json"
KAKAO_COORD2REGION_URL = "https://dapi.kakao.com/v2/local/geo/coord2regioncode.json"
KAKAO_COORD2ADDRESS_URL = "https://dapi.kakao.com/v2/local/geo/coord2address.json"

DEFAULT_LAT = 37.2118
DEFAULT_LON = 126.9765

WALK_RADIUS_METERS = 1000
DELIVERY_RADIUS_METERS = 3500

# 식사 후보 품질 저하 방지를 위해 주류/아이스크림 전문점은 후순위 제외 대상으로 분류
EXCLUDED_NON_MEAL_TOKENS = (
    "술집",
    "호프",
    "포차",
    "요리주점",
    "일본식주점",
    "단란주점",
    "유흥주점",
    "아이스크림",
    "오픈예정",
)

# 배달 주문 모드에서는 현장 식사 전용 업태(구내식당/푸드코트/뷔페/참숯구이 등)를 제외
EXCLUDED_DELIVERY_ONLY_TOKENS = (
    "구내식당",
    "학생식당",
    "직원식당",
    "사내식당",
    "학교식당",
    "푸드코트",
    "뷔페",
    "출장뷔페",
    "웨딩",
    "장례식장",
    "휴게소",
    "참숯",
    "셀프바",
)

# 카카오 로컬 API(협성대/봉담 기준) 실제 조회로 실존과 URL/좌표 거리가 검증된 대표 매장 안전 데이터
# (API 네트워크 장애/일시 오류 시에만 폴백으로 사용되며 가짜 더미 매장은 일절 포함하지 않음)
VERIFIED_REAL_RESTAURANTS: List[Dict[str, Any]] = [
    {
        "id": "1822665495",
        "place_name": "장수소머리국밥",
        "category_name": "음식점 > 한식 > 국밥",
        "distance": "203",
        "road_address_name": "경기 화성시 효행구 봉담읍 와우로 90",
        "place_url": "http://place.map.kakao.com/1822665495",
        "phone": "",
    },
    {
        "id": "92029939",
        "place_name": "상상카츠 수원대점",
        "category_name": "음식점 > 일식 > 돈까스,우동",
        "distance": "203",
        "road_address_name": "경기 화성시 효행구 봉담읍 와우로 90",
        "place_url": "http://place.map.kakao.com/92029939",
        "phone": "031-223-6326",
    },
    {
        "id": "16342336",
        "place_name": "본죽 수원대점",
        "category_name": "음식점 > 한식 > 죽 > 본죽",
        "distance": "210",
        "road_address_name": "경기 화성시 효행구 봉담읍 와우로 90",
        "place_url": "http://place.map.kakao.com/16342336",
        "phone": "031-225-6288",
    },
    {
        "id": "1946815364",
        "place_name": "신동랩 화성봉담점",
        "category_name": "음식점 > 일식",
        "distance": "214",
        "road_address_name": "경기 화성시 효행구 봉담읍 와우로 96",
        "place_url": "http://place.map.kakao.com/1946815364",
        "phone": "",
    },
    {
        "id": "9433168",
        "place_name": "챠이챠이",
        "category_name": "음식점 > 중식 > 중국요리",
        "distance": "228",
        "road_address_name": "경기 화성시 효행구 봉담읍 와우로 100",
        "place_url": "http://place.map.kakao.com/9433168",
        "phone": "031-222-0506",
    },
    {
        "id": "1286364570",
        "place_name": "버거킹 화성봉담점",
        "category_name": "음식점 > 패스트푸드 > 버거킹",
        "distance": "250",
        "road_address_name": "경기 화성시 효행구 봉담읍 와우로 80",
        "place_url": "http://place.map.kakao.com/1286364570",
        "phone": "070-7462-6818",
    },
    {
        "id": "2041404248",
        "place_name": "김찌로 수원대점",
        "category_name": "음식점 > 한식",
        "distance": "260",
        "road_address_name": "경기 화성시 효행구 봉담읍 와우로 95",
        "place_url": "http://place.map.kakao.com/2041404248",
        "phone": "010-7782-3335",
    },
    {
        "id": "1900145710",
        "place_name": "탕화쿵푸마라탕 수원대점",
        "category_name": "음식점 > 중식 > 중국요리 > 탕화쿵푸마라탕",
        "distance": "261",
        "road_address_name": "경기 화성시 효행구 봉담읍 와우로 95",
        "place_url": "http://place.map.kakao.com/1900145710",
        "phone": "",
    },
    {
        "id": "1483751652",
        "place_name": "가장맛있는족발 수원대점",
        "category_name": "음식점 > 한식 > 육류,고기 > 족발,보쌈 > 가장맛있는족발",
        "distance": "262",
        "road_address_name": "경기 화성시 효행구 봉담읍 와우로 99",
        "place_url": "http://place.map.kakao.com/1483751652",
        "phone": "",
    },
    {
        "id": "791253737",
        "place_name": "밀플랜비 수원대점",
        "category_name": "음식점 > 패스트푸드",
        "distance": "263",
        "road_address_name": "경기 화성시 효행구 봉담읍 와우로 108",
        "place_url": "http://place.map.kakao.com/791253737",
        "phone": "",
    },
    {
        "id": "76626982",
        "place_name": "청년다방 수원대점",
        "category_name": "음식점 > 분식 > 떡볶이 > 청년다방",
        "distance": "263",
        "road_address_name": "경기 화성시 효행구 봉담읍 와우로 91",
        "place_url": "http://place.map.kakao.com/76626982",
        "phone": "",
    },
    {
        "id": "609042327",
        "place_name": "신의주찹쌀순대 수원대점",
        "category_name": "음식점 > 한식 > 순대 > 신의주찹쌀순대",
        "distance": "265",
        "road_address_name": "경기 화성시 효행구 봉담읍 와우로 91",
        "place_url": "http://place.map.kakao.com/609042327",
        "phone": "",
    },
    {
        "id": "14686280",
        "place_name": "김밥천국 수원대점",
        "category_name": "음식점 > 분식",
        "distance": "275",
        "road_address_name": "경기 화성시 효행구 봉담읍 와우로 85",
        "place_url": "http://place.map.kakao.com/14686280",
        "phone": "031-233-1288",
    },
    {
        "id": "20996050",
        "place_name": "파리바게뜨 화성와우점",
        "category_name": "음식점 > 간식 > 제과,베이커리 > 파리바게뜨",
        "distance": "277",
        "road_address_name": "경기 화성시 효행구 봉담읍 와우로 85",
        "place_url": "http://place.map.kakao.com/20996050",
        "phone": "",
    },
    {
        "id": "476089736",
        "place_name": "프린샌드위치 와우리점",
        "category_name": "음식점 > 패스트푸드 > 샌드위치",
        "distance": "284",
        "road_address_name": "경기 화성시 효행구 봉담읍 와우로 110",
        "place_url": "http://place.map.kakao.com/476089736",
        "phone": "010-2878-3200",
    },
    {
        "id": "1609121754",
        "place_name": "청담뼈해장",
        "category_name": "음식점 > 한식 > 해장국",
        "distance": "299",
        "road_address_name": "경기 화성시 효행구 봉담읍 와우로 114-4",
        "place_url": "http://place.map.kakao.com/1609121754",
        "phone": "",
    },
    {
        "id": "1974959691",
        "place_name": "파스타하임",
        "category_name": "음식점 > 양식 > 이탈리안",
        "distance": "310",
        "road_address_name": "경기 화성시 효행구 봉담읍 참샘길 27",
        "place_url": "http://place.map.kakao.com/1974959691",
        "phone": "",
    },
    {
        "id": "492003036",
        "place_name": "최고당돈가스 수원대점",
        "category_name": "음식점 > 일식 > 돈까스,우동 > 최고당돈가스",
        "distance": "311",
        "road_address_name": "경기 화성시 효행구 봉담읍 와우로73번길 6",
        "place_url": "http://place.map.kakao.com/492003036",
        "phone": "031-222-9403",
    },
    {
        "id": "479406570",
        "place_name": "일품양평해장국 수원대점",
        "category_name": "음식점 > 한식 > 해장국 > 일품양평해장국",
        "distance": "341",
        "road_address_name": "경기 화성시 효행구 봉담읍 와우안길 33",
        "place_url": "http://place.map.kakao.com/479406570",
        "phone": "031-222-5147",
    },
    {
        "id": "11634970",
        "place_name": "한솥도시락 수원대점",
        "category_name": "음식점 > 도시락 > 한솥도시락",
        "distance": "357",
        "road_address_name": "경기 화성시 효행구 봉담읍 와우안길 26-1",
        "place_url": "http://place.map.kakao.com/11634970",
        "phone": "031-225-4544",
    },
    {
        "id": "26236622",
        "place_name": "맘스터치 수원대점",
        "category_name": "음식점 > 패스트푸드 > 맘스터치",
        "distance": "362",
        "road_address_name": "경기 화성시 효행구 봉담읍 와우안길 22",
        "place_url": "http://place.map.kakao.com/26236622",
        "phone": "031-239-1009",
    },
    {
        "id": "2057210511",
        "place_name": "에그2000 화성봉담점",
        "category_name": "음식점 > 패스트푸드 > 샌드위치 > 에그2000",
        "distance": "378",
        "road_address_name": "경기 화성시 효행구 봉담읍 참샘길 8",
        "place_url": "http://place.map.kakao.com/2057210511",
        "phone": "031-8065-7092",
    },
    {
        "id": "943124732",
        "place_name": "행컵 수원대학교점",
        "category_name": "음식점 > 한식 > 행컵",
        "distance": "407",
        "road_address_name": "경기 화성시 효행구 봉담읍 와우안길 43",
        "place_url": "http://place.map.kakao.com/943124732",
        "phone": "031-898-6181",
    },
    {
        "id": "1558253501",
        "place_name": "미소야 봉담와우점",
        "category_name": "음식점 > 일식 > 돈까스,우동 > 미소야",
        "distance": "749",
        "road_address_name": "경기 화성시 효행구 봉담읍 와우로 20",
        "place_url": "http://place.map.kakao.com/1558253501",
        "phone": "031-222-1990",
    },
    {
        "id": "801547801",
        "place_name": "봉구스밥버거 와우고점",
        "category_name": "음식점 > 한식 > 주먹밥 > 봉구스밥버거",
        "distance": "1080",
        "road_address_name": "경기 화성시 효행구 봉담읍 동화서북안길 10",
        "place_url": "http://place.map.kakao.com/801547801",
        "phone": "010-2452-3703",
    },
    {
        "id": "1660473544",
        "place_name": "베트남노상식당 딜리버리 경기봉담점",
        "category_name": "음식점 > 아시아음식 > 동남아음식 > 베트남음식 > 베트남노상식당",
        "distance": "1100",
        "road_address_name": "경기 화성시 효행구 봉담읍 와우안길 109",
        "place_url": "http://place.map.kakao.com/1660473544",
        "phone": "031-222-4933",
    },
    {
        "id": "1137776580",
        "place_name": "인더비엣 봉담점",
        "category_name": "음식점 > 아시아음식 > 동남아음식 > 베트남음식",
        "distance": "2024",
        "road_address_name": "경기 화성시 효행구 봉담읍 동화길 51",
        "place_url": "http://place.map.kakao.com/1137776580",
        "phone": "031-5183-3814",
    },
    {
        "id": "800366658",
        "place_name": "포케올데이 봉담점",
        "category_name": "음식점 > 샐러드 > 포케올데이",
        "distance": "2830",
        "road_address_name": "경기 화성시 효행구 봉담읍 장등2길 6-11",
        "place_url": "http://place.map.kakao.com/800366658",
        "phone": "070-7585-4914",
    },
    {
        "id": "47636247",
        "place_name": "샐러리아 봉담점",
        "category_name": "음식점 > 샐러드 > 샐러리아",
        "distance": "2834",
        "road_address_name": "경기 화성시 효행구 봉담읍 장등2길 6-10",
        "place_url": "http://place.map.kakao.com/47636247",
        "phone": "031-293-0988",
    },
]


class KakaoServiceError(RuntimeError):
    """카카오 로컬 API 호출 실패 또는 권한/설정 오류를 나타내는 예외."""


def haversine_meters(lat1: float, lon1: float, lat2: float, lon2: float) -> int:
    """두 WGS84 좌표 간 직선 거리(미터)를 하버사인 공식으로 계산합니다."""
    earth_radius_m = 6371000.0
    phi1 = math.radians(lat1)
    phi2 = math.radians(lat2)
    d_phi = math.radians(lat2 - lat1)
    d_lambda = math.radians(lon2 - lon1)
    a = (
        math.sin(d_phi / 2.0) ** 2
        + math.cos(phi1) * math.cos(phi2) * math.sin(d_lambda / 2.0) ** 2
    )
    c = 2.0 * math.asin(min(1.0, math.sqrt(a)))
    return round(earth_radius_m * c)


def get_search_bounds(delivery_mode: str) -> Tuple[int, int]:
    """식사 방식('walk' / 'delivery')별 search_radius와 max_cutoff를 완전 격리해 반환합니다."""
    if delivery_mode == "delivery":
        search_radius = DELIVERY_RADIUS_METERS  # 배달 반경 3.5km (가까운 1km 포함)
        max_cutoff = DELIVERY_RADIUS_METERS
    else:
        search_radius = WALK_RADIUS_METERS  # 직선 1km -> 실제 보행 거리 약 1.3km (도보 18분 이내)
        max_cutoff = WALK_RADIUS_METERS
    return search_radius, max_cutoff


def get_radius_by_mode(delivery_mode: str) -> int:
    """식사 방식('walk' / 'delivery')에 따른 탐색 반경(m)을 반환합니다."""
    search_radius, _ = get_search_bounds(delivery_mode)
    return search_radius


def get_address_from_coords(lat: float, lon: float) -> str:
    """위도·경도 좌표를 카카오 역지오코딩으로 변환해 한글 행정구역 주소를 반환합니다."""
    api_key = os.getenv("KAKAO_REST_API_KEY", "").strip()
    is_default_area = haversine_meters(lat, lon, DEFAULT_LAT, DEFAULT_LON) <= 3000
    fallback_addr = (
        "경기도 화성시 효행구 봉담읍"
        if is_default_area
        else f"현재 위치 ({lat:.4f}, {lon:.4f})"
    )

    if not api_key:
        return fallback_addr

    headers = {"Authorization": f"KakaoAK {api_key}"}
    params = {"x": f"{lon:.7f}", "y": f"{lat:.7f}"}

    try:
        resp = requests.get(
            KAKAO_COORD2REGION_URL,
            headers=headers,
            params=params,
            timeout=4,
        )
        if resp.status_code == 200:
            docs = resp.json().get("documents", [])
            preferred_h = next(
                (d for d in docs if d.get("region_type") == "H" and d.get("address_name")),
                None,
            )
            if preferred_h:
                return str(preferred_h["address_name"]).strip()
            preferred_b = next(
                (d for d in docs if d.get("region_type") == "B" and d.get("address_name")),
                None,
            )
            if preferred_b:
                return str(preferred_b["address_name"]).strip()
    except Exception as exc:
        logger.warning("카카오 coord2regioncode 역지오코딩 실패(%s)", exc)

    try:
        resp_addr = requests.get(
            KAKAO_COORD2ADDRESS_URL,
            headers=headers,
            params=params,
            timeout=4,
        )
        if resp_addr.status_code == 200:
            docs = resp_addr.json().get("documents", [])
            if docs:
                addr_obj = docs[0].get("address") or {}
                parts = [
                    str(addr_obj.get("region_1depth_name", "")).strip(),
                    str(addr_obj.get("region_2depth_name", "")).strip(),
                    str(addr_obj.get("region_3depth_name", "")).strip(),
                ]
                joined = " ".join(p for p in parts if p)
                if joined:
                    return joined
    except Exception as exc:
        logger.warning("카카오 coord2address 역지오코딩 실패(%s)", exc)

    return fallback_addr


def search_location_candidates(query: str) -> List[Dict[str, Any]]:
    """
    PC/네트워크 IP 오차로 잘못된 지역이 잡혔을 때 사용자가 동네/역/건물명으로
    실제 기준 위치를 직접 지정할 수 있도록 카카오 주소·장소 후보를 최대 5건 반환합니다.
    """
    cleaned = str(query or "").strip()
    if not cleaned:
        return []

    api_key = os.getenv("KAKAO_REST_API_KEY", "").strip()
    if not api_key:
        return []

    headers = {"Authorization": f"KakaoAK {api_key}"}
    results: List[Dict[str, Any]] = []
    seen = set()

    try:
        addr_resp = requests.get(
            KAKAO_LOCAL_ADDRESS_URL,
            headers=headers,
            params={"query": cleaned, "size": 2},
            timeout=4,
        )
        if addr_resp.status_code == 200:
            for doc in addr_resp.json().get("documents", []):
                addr_name = str(doc.get("address_name", "")).strip()
                raw_x, raw_y = doc.get("x"), doc.get("y")
                if not addr_name or not raw_x or not raw_y:
                    continue
                try:
                    lat_v, lon_v = float(raw_y), float(raw_x)
                except (TypeError, ValueError):
                    continue
                key = (addr_name, round(lat_v, 4), round(lon_v, 4))
                if key not in seen:
                    seen.add(key)
                    results.append(
                        {
                            "place_name": addr_name,
                            "address_name": addr_name,
                            "latitude": lat_v,
                            "longitude": lon_v,
                        }
                    )
    except Exception as exc:
        logger.warning("카카오 주소 검색 실패(%s)", exc)

    try:
        kw_resp = requests.get(
            KAKAO_LOCAL_KEYWORD_URL,
            headers=headers,
            params={"query": cleaned, "size": 5},
            timeout=4,
        )
        if kw_resp.status_code == 200:
            for doc in kw_resp.json().get("documents", []):
                place_name = str(doc.get("place_name", "")).strip()
                addr_name = str(
                    doc.get("road_address_name") or doc.get("address_name") or ""
                ).strip()
                raw_x, raw_y = doc.get("x"), doc.get("y")
                if not place_name or not raw_x or not raw_y:
                    continue
                try:
                    lat_v, lon_v = float(raw_y), float(raw_x)
                except (TypeError, ValueError):
                    continue
                key = (place_name, round(lat_v, 4), round(lon_v, 4))
                if key not in seen:
                    seen.add(key)
                    results.append(
                        {
                            "place_name": place_name,
                            "address_name": addr_name or place_name,
                            "latitude": lat_v,
                            "longitude": lon_v,
                        }
                    )
    except Exception as exc:
        logger.warning("카카오 키워드 위치 검색 실패(%s)", exc)

    return results[:5]


def _get_verified_backup_restaurants(
    lat: float, lon: float, delivery_mode: str
) -> List[Dict[str, Any]]:
    """
    카카오 API 실패/미설정 시, 좌표가 기본 기준권(협성대 2.5km 이내)인 경우에만
    반경 컷오프에 맞는 실존 검증 대표 매장 목록을 반환합니다.
    """
    if haversine_meters(lat, lon, DEFAULT_LAT, DEFAULT_LON) > 2500:
        raise KakaoServiceError(
            "현재 GPS 위치 기준으로 주변 카카오 식당 정보를 불러오지 못했습니다. 잠시 후 다시 시도해주세요."
        )

    _, max_cutoff = get_search_bounds(delivery_mode)
    filtered = [
        dict(item)
        for item in VERIFIED_REAL_RESTAURANTS
        if 0 <= int(item["distance"]) <= max_cutoff
    ]
    return filtered[:45]


def _select_enrichment_keywords(
    texture_temp: Optional[str], meal_mode: Optional[str]
) -> List[str]:
    """정석(3-Tap 맞춤)과 리프레시(카테고리 변주 대안) 실존 매장을 함께 보강 검색합니다."""
    if meal_mode == "clean":
        if texture_temp == "soup":
            return ["쌀국수", "우동", "국밥", "샤브", "포케"]
        if texture_temp == "bread":
            return ["샌드위치", "샐러드", "토스트", "포케"]
        return ["포케", "샐러드", "죽", "덮밥", "샌드위치"]

    keywords: List[str] = []
    if texture_temp == "bread":
        target = ["버거", "샌드위치", "토스트", "도시락", "샐러드"]
    elif texture_temp == "soup":
        target = ["국밥", "찌개", "우동", "쌀국수", "돈까스"]
    elif texture_temp == "rice":
        target = ["도시락", "덮밥", "김밥", "샌드위치", "파스타"]
    else:
        target = ["버거", "국밥", "덮밥"]

    for kw in target:
        if kw not in keywords:
            keywords.append(kw)
    return keywords


def _is_non_meal_venue(
    place_name: str, category_name: str, *, delivery_mode: str = "walk"
) -> bool:
    combined = f"{place_name} {category_name}"
    if any(tok in combined for tok in EXCLUDED_NON_MEAL_TOKENS):
        return True
    if delivery_mode == "delivery" and any(
        tok in combined for tok in EXCLUDED_DELIVERY_ONLY_TOKENS
    ):
        return True
    return False


def _normalize_doc(
    doc: Dict[str, Any], lat: float, lon: float, max_cutoff: int
) -> Optional[Dict[str, Any]]:
    """
    카카오 API 응답 문서를 정규화하며, 전국 검색 버그를 원천 차단하기 위해
    카카오 보고 거리(distance) 및 실좌표 기반 하버사인 거리를 이중 검증해 max_cutoff 초과 매장을 배제합니다.
    """
    place_name = str(doc.get("place_name", "")).strip()
    if not place_name:
        return None

    hav_m: Optional[int] = None
    raw_x = str(doc.get("x", "")).strip()
    raw_y = str(doc.get("y", "")).strip()
    if raw_x and raw_y:
        try:
            doc_lon = float(raw_x)
            doc_lat = float(raw_y)
            if not (-90.0 <= doc_lat <= 90.0 and -180.0 <= doc_lon <= 180.0):
                return None
            hav_m = haversine_meters(lat, lon, doc_lat, doc_lon)
        except ValueError:
            return None

    raw_distance = str(doc.get("distance", "")).strip()
    if raw_distance:
        try:
            dist_m = int(float(raw_distance))
        except ValueError:
            return None
    elif hav_m is not None:
        dist_m = hav_m
    else:
        return None

    # 전국 검색 및 반경 초과 데이터 이중 차단
    if dist_m < 0 or dist_m > max_cutoff:
        return None
    if hav_m is not None and hav_m > (max_cutoff + 30):
        return None

    place_url = (
        str(doc.get("place_url", "")).strip()
        or f"https://map.kakao.com/link/search/{quote(place_name)}"
    )
    return {
        "id": str(doc.get("id", "")),
        "place_name": place_name,
        "category_name": doc.get("category_name", "음식점"),
        "distance": str(dist_m),
        "road_address_name": doc.get("road_address_name")
        or doc.get("address_name", ""),
        "place_url": place_url,
        "phone": doc.get("phone", ""),
        "_dist_int": dist_m,
    }


def get_nearby_restaurants(
    lat: float,
    lon: float,
    delivery_mode: str = "walk",
    texture_temp: Optional[str] = None,
    meal_mode: Optional[str] = None,
) -> List[Dict[str, Any]]:
    """
    카카오 로컬 REST API(FD6 category page=1, 2, 3 + 반경 잠금 keyword 보강)를 결합해
    모드별 반경 내 실제 주변 식사 매장을 수집합니다.
    - delivery_mode == 'walk': search_radius=1000, max_cutoff=1000 (직선 1km -> 실보행 약 1.3km, 도보 18분 이내)
    - delivery_mode == 'delivery': search_radius=3500, max_cutoff=3500 (가까운 1km 포함 최대 3.5km)
    - 모든 API 요청에 x, y, radius, category_group_code='FD6' 및 하버사인 거리 검증을 강제해 전국 검색 버그를 차단합니다.
    """
    mode = "delivery" if delivery_mode == "delivery" else "walk"
    search_radius, max_cutoff = get_search_bounds(mode)

    api_key = os.getenv("KAKAO_REST_API_KEY", "").strip()
    if not api_key:
        logger.warning("KAKAO_REST_API_KEY 미설정 - 실존 검증 안전 매장 목록을 확인합니다.")
        return _get_verified_backup_restaurants(lat, lon, mode)

    headers = {"Authorization": f"KakaoAK {api_key}"}

    meal_pool: List[Dict[str, Any]] = []
    enrichment_pool: List[Dict[str, Any]] = []
    secondary_pool: List[Dict[str, Any]] = []
    seen_ids = set()
    seen_names = set()
    category_call_succeeded = False

    def _ingest_documents(
        documents: List[Dict[str, Any]], *, is_enrichment: bool = False
    ) -> None:
        for doc in documents:
            normalized = _normalize_doc(doc, lat, lon, max_cutoff)
            if not normalized:
                continue
            unique_key = normalized["id"] or normalized["place_name"]
            norm_name_key = "".join(normalized["place_name"].split()).lower()
            if unique_key in seen_ids or norm_name_key in seen_names:
                if is_enrichment:
                    for existing in meal_pool:
                        existing_name_key = "".join(existing["place_name"].split()).lower()
                        if (existing["id"] or existing["place_name"]) == unique_key or existing_name_key == norm_name_key:
                            if existing not in enrichment_pool:
                                enrichment_pool.append(existing)
                            break
                continue
            seen_ids.add(unique_key)
            seen_names.add(norm_name_key)
            if _is_non_meal_venue(
                normalized["place_name"],
                normalized["category_name"],
                delivery_mode=mode,
            ):
                secondary_pool.append(normalized)
            else:
                meal_pool.append(normalized)
                if is_enrichment:
                    enrichment_pool.append(normalized)

    # 1) 기본 FD6 카테고리 거리순 page=1, 2, 3 수집 (반경 내 근거리 매장 전수 확보)
    for page in (1, 2, 3):
        params = {
            "category_group_code": "FD6",
            "x": f"{lon:.7f}",
            "y": f"{lat:.7f}",
            "radius": search_radius,
            "sort": "distance",
            "size": 15,
            "page": page,
        }
        try:
            response = requests.get(
                KAKAO_LOCAL_CATEGORY_URL,
                headers=headers,
                params=params,
                timeout=5,
            )
            if response.status_code != 200:
                logger.warning(
                    "카카오 로컬 API 카테고리 %d페이지 오류(%d): %s",
                    page,
                    response.status_code,
                    response.text[:200],
                )
                break

            category_call_succeeded = True
            data = response.json()
        except Exception as exc:
            logger.warning("카카오 로컬 API 카테고리 %d페이지 호출/파싱 실패(%s)", page, exc)
            break

        documents = data.get("documents", [])
        if not documents:
            break

        _ingest_documents(documents)
        if data.get("meta", {}).get("is_end", False):
            break

    # 2) 반경 고정 3-Tap 맞춤 키워드 검색
    # - walk(1.5km): 거리순(distance)으로 도보권 내 최적 매장 집중 보강
    # - delivery(3.5km): accuracy(반경 3500m 잠금)로 가까운 1.5km 이내부터 1.5~3.5km 인기 배달 매장까지 골고루 수집
    if category_call_succeeded:
        kw_sort = "accuracy" if mode == "delivery" else "distance"
        kw_size = 10 if mode == "delivery" else 8
        for kw in _select_enrichment_keywords(texture_temp, meal_mode):
            kw_params = {
                "query": kw,
                "category_group_code": "FD6",
                "x": f"{lon:.7f}",
                "y": f"{lat:.7f}",
                "radius": search_radius,
                "sort": kw_sort,
                "size": kw_size,
            }
            try:
                kw_resp = requests.get(
                    KAKAO_LOCAL_KEYWORD_URL,
                    headers=headers,
                    params=kw_params,
                    timeout=4,
                )
                if kw_resp.status_code == 200:
                    _ingest_documents(
                        kw_resp.json().get("documents", []),
                        is_enrichment=True,
                    )
            except Exception as exc:
                logger.warning("카카오 키워드('%s') 보강 검색 실패(%s)", kw, exc)

    if not meal_pool and not secondary_pool:
        logger.warning("카카오 로컬 API 결과 없음/실패 - 안전 백업을 확인합니다.")
        return _get_verified_backup_restaurants(lat, lon, mode)

    # 키워드 보강 풀(최대 30개)과 근거리 일반 식사 매장을 결합해 최대 45개 후보군 구성
    # 배달 모드에서는 가까운 매장으로만 포화되지 않도록 원거리(>1km) 보강 매장도 균형 반영
    selected: List[Dict[str, Any]] = []
    selected_keys = set()
    if mode == "delivery":
        far_enriched = sorted(
            [x for x in enrichment_pool if x["_dist_int"] > 1000],
            key=lambda x: x["_dist_int"],
        )[:15]
        near_enriched = sorted(
            [x for x in enrichment_pool if x["_dist_int"] <= 1000],
            key=lambda x: x["_dist_int"],
        )[:20]
        ordered_pools = (
            far_enriched,
            near_enriched,
            sorted(meal_pool, key=lambda x: x["_dist_int"]),
        )
    else:
        ordered_pools = (
            enrichment_pool[:30],
            sorted(meal_pool, key=lambda x: x["_dist_int"]),
        )

    for pool in ordered_pools:
        for item in pool:
            if len(selected) >= 45:
                break
            k = item["id"] or item["place_name"]
            if k not in selected_keys:
                selected_keys.add(k)
                selected.append(item)

    min_fill = 5 if mode == "delivery" else 20
    if len(selected) < min_fill and secondary_pool:
        for item in sorted(secondary_pool, key=lambda x: x["_dist_int"]):
            if len(selected) >= 45:
                break
            k = item["id"] or item["place_name"]
            if k not in selected_keys:
                selected_keys.add(k)
                selected.append(item)

    selected.sort(key=lambda x: x["_dist_int"])
    return [{k: v for k, v in item.items() if k != "_dist_int"} for item in selected]


def _match_emoji_from_text(text: str, *, include_broad_category: bool = True) -> Optional[str]:
    """메뉴·상호·카테고리 문자열을 우선순위에 따라 분석해 대표 푸드 이모지를 반환합니다."""
    if not text:
        return None

    # 0. 부리또 / 브리또 / 타코 / 퀘사디아 / 랩 (피자·치킨·샐러드 등 복합 메뉴명보다 최우선 매칭; 신동랩·크랩·타코야끼·~Lab 상호 제외)
    burrito_text = re.sub(
        r"(?:신동랩|킹크랩|스노우크랩|소프트크랩|게살크랩|크랩|타코야[끼키]|(?:푸드|버거|피자|파스타|초밥|스시|고기|브레드|베이킹|쿠킹|키친|커피|디저트|샌드위치)랩)",
        "",
        text,
    )
    if any(
        kw in burrito_text
        for kw in (
            "부리또",
            "브리또",
            "타코",
            "퀘사디아",
            "밀플랜비",
        )
    ) or re.search(
        r"(?:샐러드|치킨|비프|소고기|돼지고기|포크|불고기|스테이크|새우|햄에그|야채|베지|에그|또띠아|스낵|멕시칸|치폴레|아보카도|포케|케밥|닭가슴살|참치|단백질|런치|모닝|브런치)랩|(?:^|\s|·|,|/|\+)랩(?=$|\s|·|,|/|\+)",
        burrito_text,
    ):
        return "🌯"

    # 1. 토스트 / 샌드위치 (패스트푸드 카테고리 하위 샌드위치 브랜드 오매칭 방지 위해 우선)
    if any(
        kw in text
        for kw in (
            "토스트",
            "샌드위치",
            "이삭",
            "에그드랍",
            "에그2000",
            "써브웨이",
            "서브웨이",
            "파니니",
            "베이글",
            "파리바게뜨",
            "베이커리",
        )
    ):
        return "🥪"

    # 2. 샐러드 / 포케
    if any(kw in text for kw in ("샐러드", "포케", "샐러리아", "샐러디", "웜볼")):
        return "🥗"

    # 3. 피자 / 파스타 / 양식 (면 토큰 오매칭 방지 위해 면류보다 우선)
    if any(kw in text for kw in ("피자", "파스타", "스파게티", "리조또")):
        return "🍕"

    # 4. 덮밥 / 도시락 / 밥류 / 한솥 (밥버거·치킨마요·제육덮밥 등 복합어 오매칭 방지; 사이드 '공기밥'은 후순위로 분리)
    if any(
        kw in text
        for kw in (
            "밥버거",
            "봉구스",
            "덮밥",
            "도시락",
            "한솥",
            "컵밥",
            "행컵",
            "볶음밥",
            "비빔밥",
            "알밥",
            "백반",
            "주먹밥",
            "라이스",
        )
    ):
        return "🍱"

    # 5. 버거 / 와퍼 / 패스트푸드 (밥버거는 위에서 처리됨)
    has_burger_brand = any(
        kw in text
        for kw in (
            "와퍼",
            "버거킹",
            "맘스터치",
            "맥도날드",
            "롯데리아",
            "노브랜드버거",
            "프랭크버거",
            "왓더버거",
            "햄버거",
            "수제버거",
            "싸이버거",
            "싸이",
        )
    )
    has_burger_word = "버거" in text and "밥버거" not in text
    if has_burger_brand or has_burger_word:
        return "🍔"

    # 6. 돈까스 / 카츠 (일식 카테고리의 돈까스,우동 중 메뉴명 기준 우선 판단)
    if any(kw in text for kw in ("돈까스", "돈가스", "카츠", "가츠", "카레")):
        return "🍛"

    # 7. 치킨 / 닭강정 (버거류 제외 후 판단)
    if any(
        kw in text
        for kw in (
            "치킨",
            "닭강정",
            "통닭",
            "후라이드",
            "교촌",
            "굽네",
            "푸라닭",
            "지코바",
        )
    ):
        return "🍗"

    # 8. 면 / 라면 / 우동 / 짬뽕 / 국수 (마라탕/쌀국수 포함; 찌개·전골 사이드 '라면사리/면사리' 등 제외)
    noodle_text = re.sub(r"(?:라면|우동|당면|쫄면|면)사리", "", text)
    if any(
        kw in noodle_text
        for kw in (
            "라면",
            "우동",
            "짬뽕",
            "국수",
            "쌀국수",
            "칼국수",
            "라멘",
            "마라탕",
            "탕화쿵푸",
            "라홍방",
            "짜장",
            "냉면",
            "쫄면",
            "라볶이",
            "면",
        )
    ):
        return "🍜"

    # 9. 국밥 / 탕 / 찌개 / 설렁탕
    if any(
        kw in text
        for kw in (
            "국밥",
            "설렁탕",
            "해장국",
            "뼈해장",
            "소머리",
            "순대국",
            "갈비탕",
            "육개장",
            "감자탕",
            "찌개",
            "김치찌개",
            "김찌로",
            "부대찌개",
            "순두부",
            "전골",
            "탕",
            "본죽",
            "죽",
        )
    ):
        return "🍲"

    # 10. 제육 / 불고기 / 두루치기 / 고기류
    if any(
        kw in text
        for kw in (
            "제육",
            "불고기",
            "두루치기",
            "족발",
            "보쌈",
            "삼겹",
            "갈비",
            "수육",
            "스테이크",
        )
    ):
        return "🥩"

    # 11. 분식 / 떡볶이
    if any(kw in text for kw in ("떡볶이", "청년다방", "김밥", "분식", "순대")):
        return "🍢"

    # 12. 사이드 공기밥은 국밥·찌개·탕·면 등 메인 요리가 없을 때만 후순위로 매칭
    if "공기밥" in text:
        return "🍱"

    if include_broad_category:
        if "패스트푸드" in text:
            return "🍔"
        if "양식" in text or "이탈리안" in text:
            return "🍕"
        if "일식" in text:
            return "🍛"
        if "고기" in text or "육류" in text:
            return "🥩"
        if "밥" in text:
            return "🍱"

    return None


def get_menu_emoji(
    restaurant_name: str = "",
    menu_name: str = "",
    category_name: str = "",
) -> str:
    """메뉴명·상호명·카테고리를 분석해 토스 스타일의 깔끔한 푸드 이모지 엠블럼을 반환합니다."""
    r_name = str(restaurant_name or "").strip()
    m_name = str(menu_name or "").strip()
    c_name = str(category_name or "").strip()

    # 1차: 사이드('+ 공기밥 추가', '+ 어묵탕' 등)를 제외한 메인 메뉴명(첫 '+' 이전) + 상호명 기준 정밀 매칭
    main_menu = m_name.split("+", 1)[0].strip() if "+" in m_name else m_name
    main_match = _match_emoji_from_text(
        f"{main_menu} {r_name}", include_broad_category=False
    )
    if main_match:
        return main_match

    # 2차: 전체 메뉴명 + 상호명 기준 정밀 매칭 (카테고리에 '돈까스,우동'이나 '패스트푸드'가 섞여도 정확히 구분)
    if main_menu != m_name:
        primary_match = _match_emoji_from_text(
            f"{m_name} {r_name}", include_broad_category=False
        )
        if primary_match:
            return primary_match

    # 3차: 카테고리까지 포함한 전체 컨텍스트 매칭
    full_match = _match_emoji_from_text(
        f"{m_name} {r_name} {c_name}", include_broad_category=True
    )
    return full_match or "🍽️"


NAVER_MOBILE_SEARCH_URL = "https://m.search.naver.com/search.naver"

_NAVER_SPECIAL_CHARS_RE = re.compile(r"[&+·ㆍ•・/|,\-_~()\[\]{}]+")

_NON_BRANCH_DOT_SUFFIXES = (
    "반점",
    "과자점",
    "정육점",
    "문구점",
    "복권방",
    "음식점",
    "전문점",
    "할인점",
    "편의점",
    "면세점",
    "백화점",
)


def _extract_admin_dong(address_name: str = "") -> str:
    """행정구역 주소 문자열에서 행정동·읍·면(우선) 또는 리·가 명칭을 추출합니다."""
    text = re.sub(r"\s+", " ", str(address_name or "")).strip()
    if not text:
        return ""
    primary_tokens = re.findall(r"[가-힣]+[0-9]*(?:읍|면|동)(?=\s|$)", text)
    if primary_tokens:
        return primary_tokens[0]
    secondary_tokens = re.findall(r"[가-힣]+[0-9]*(?:리|가)(?=\s|$)", text)
    if secondary_tokens:
        return secondary_tokens[-1]
    return ""


def _extract_region_stems(address_name: str = "") -> List[str]:
    """행정구역 주소에서 시·군·구·읍·면·동·리 단위의 2글자 이상 지역 키워드를 추출합니다."""
    text = re.sub(r"\s+", " ", str(address_name or "")).strip()
    if not text:
        return []
    stems: List[str] = []
    for tok in re.findall(r"[가-힣]+[0-9]*(?:시|군|구|읍|면|동|리|가)(?=\s|$)", text):
        if tok not in stems:
            stems.append(tok)
        stem = re.sub(r"[0-9]*(?:시|군|구|읍|면|동|리|가)$", "", tok)
        if len(stem) >= 2 and stem not in stems:
            stems.append(stem)
    return stems


def _has_branch_or_region_name(
    store_name: str, dong_name: str = "", address_name: str = ""
) -> bool:
    """상호명에 지점명('점', '본점' 등)이나 지역명이 이미 포함되어 있는지 판별합니다."""
    clean_store = re.sub(r"\s+", " ", str(store_name or "")).strip()
    if not clean_store:
        return False

    if dong_name and dong_name in clean_store:
        return True

    region_source = f"{address_name} {dong_name}".strip()
    for term in _extract_region_stems(region_source):
        if re.search(rf"(?:^|\s){re.escape(term)}", clean_store):
            return True

    tokens = clean_store.split()
    last_token = tokens[-1]
    is_non_branch_word = any(
        last_token.endswith(suffix) for suffix in _NON_BRANCH_DOT_SUFFIXES
    )

    # 띄어쓰기 뒤 지점명 (예: "한솥도시락 수원대점", "포케올데이 봉담점", "신전떡볶이 본점")
    if len(tokens) >= 2 and last_token.endswith("점") and not is_non_branch_word:
        return True

    # 공백 없는 지점명 결합 (예: "이디야봉담점", "스타벅스본점", "카페직영점")
    dong_stem = re.sub(r"[0-9]*(?:읍|면|동|리|가)$", "", dong_name or "")
    if not is_non_branch_word and clean_store.endswith("점") and len(clean_store) > 3:
        if dong_stem and len(dong_stem) >= 2 and f"{dong_stem}점" in clean_store:
            return True
        if re.search(r"(?:본점|직영점|[0-9]+호점|[가-힣0-9]+(?:역|대|호|본)점)$", clean_store):
            return True

    return False


def _sanitize_naver_store_name(store_name: str) -> str:
    """
    상호명 내 URL 깨짐을 유발하는 특수문자(&, +, · 등)만 공백으로 치환하고,
    어떤 단어도 자르거나 생략하지 않은 정제된 풀 상호명 전체를 그대로 반환합니다.
    """
    cleaned = _NAVER_SPECIAL_CHARS_RE.sub(" ", str(store_name or ""))
    return re.sub(r"\s+", " ", cleaned).strip()


def _build_naver_search_query(store_name: str, address_name: str = "") -> str:
    """지점명·지역명 여부에 따라 정제된 풀 상호명 '{clean_store}' 또는 '{dong_name} {clean_store}' 검색어를 생성합니다."""
    clean_store = _sanitize_naver_store_name(store_name)
    if not clean_store:
        return ""
    dong_name = _extract_admin_dong(address_name)
    if not dong_name or _has_branch_or_region_name(
        clean_store, dong_name=dong_name, address_name=address_name
    ):
        return clean_store
    return f"{dong_name} {clean_store}"


def resolve_naver_review_url(store_name: str, address_name: str = "") -> str:
    """
    네이버 포털 모바일 검색(`m.search.naver.com`) URL을 생성합니다.
    스마트플레이스 홈 카드(방문자 리뷰·별점·사진·메뉴)가 상단에 즉시 노출되도록
    특수문자만 공백으로 정제한 풀 상호명 전체를 그대로 검색 쿼리에 전달합니다.
    """
    query_text = _build_naver_search_query(store_name, address_name=address_name)
    if not query_text:
        return "https://m.search.naver.com/"
    return f"{NAVER_MOBILE_SEARCH_URL}?query={quote(query_text)}"
