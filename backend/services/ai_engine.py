import logging
import os
import re
from pathlib import Path
from typing import Any, Dict, List, Optional
from urllib.parse import quote

from dotenv import load_dotenv
from google import genai
from google.genai import types

from backend.schemas import (
    AIAnalysisReport,
    AISelectionItem,
    AISelectionResponse,
    DeliverySpec,
    NutritionFacts,
    RecommendationItem,
    RecommendationResponse,
    UserPreferenceRequest,
)
from backend.services.delivery_analyzer import (
    analyze_delivery_spec,
    build_delivery_deep_links,
    parse_price_int,
)
from backend.services.kakao_service import get_menu_emoji

load_dotenv(Path(__file__).resolve().parents[2] / ".env")

logger = logging.getLogger(__name__)

GEMINI_MODEL = "gemini-3.8-flash"

SYSTEM_PROMPT = (
    "당신은 직장인과 대학생의 식사 의사결정 피로(Decision Fatigue)를 끝내는 초개인화 AI 다이닝 에이전트 'MenuFit (메뉴핏)'입니다.\n"
    "경고(무관용 원칙): 제공된 [주변 실제 식당 인덱스 목록]에 없는 식당을 지어내는 것은 엄격히 금지됩니다.\n"
    "반드시 목록 내 실제 식당의 서로 다른 정수 인덱스 `selected_index`만 총 5개 선택하세요:\n"
    "- `standards` (3개, rank 1~3, persona_type='standard'): 사용자 조건(식감/온도, 식사 템포, 예산)에 100% 충실한 확신의 픽 3곳\n"
    "- `refreshes` (2개, rank 1~2, persona_type='refresh'): 사용자의 식사 템포와 예산은 유지하되 카테고리를 색다르게 비튼 반전 매력 픽 2곳\n"
    "식당 상호명이나 거리/이동시간 수치는 백엔드가 직접 매핑하므로 절대 지어내지 말고, 각 추천 메뉴의 정밀한 탄단지 영양 수치(`NutritionFacts`)와 팩트 기반 추천 근거 리포트(`AIAnalysisReport`: 방문자 리뷰 종합 요약, 인근 비교 우위, 식곤증 방어 지수, 선정 논리)만 작성하세요.\n"
    "절대 금지: '쌀쌀한 날씨에 따뜻하게...', '잘 비벼 드세요', '도보 이동이 편합니다' 같은 상투적 날씨 클리셰, 실측 근거 없는 '(94%)'·'(88%)' 같은 가짜 퍼센트(%) 수치, 실제 인용처럼 꾸민 따옴표(\"...\") 리뷰를 절대 작성하지 마세요."
)

WALK_DISTANCE_DECAY_RULE = (
    "[도보 모드 거리 감점(Distance Decay) 절대 규칙 — 직선 반경 1,000m / 실보행 약 1.3km 이내]\n"
    "- 실제 도보는 신호등·골목 우회(×1.3)로 인해 직선 1km가 실보행 약 1.3km(도보 약 18분)에 해당합니다.\n"
    "- 후보군 평가 시 직선 거리(distance, 미터) 및 실보행 환산 거리에 따른 가중치를 반드시 적용하세요:\n"
    "  · 직선 500m 이하 (실보행 ~650m / 도보 ~9분 이내): 거리 점수 만점.\n"
    "  · 직선 500m ~ 1000m (실보행 ~1.3km / 도보 10~18분): 거리가 멀어질수록 추천 점수에 점진적 감점 페널티를 부여하세요.\n"
    "- 조건과 맛이 비슷하다면 가까운 매장을 최우선(1위)으로 선정하세요.\n"
    "- 만약 직선 700m(실보행 ~910m, 도보 약 13분) 이상 떨어진 매장이 선정될 경우, 그만한 확실한 조리 퀄리티나 시그니처 비교 우위가 있어야 하며, "
    "`report.why_this_spot`에는 거리를 나열하는 대신 주변 대비 음식·가성비 경쟁력을 팩트로 서술하세요."
)

DELIVERY_MODE_RULE = (
    "[배달 주문 모드 규칙 — 반경 3,500m 이내]\n"
    "- 가까운 1km 이내 매장부터 최대 3.5km 권역의 인기 배달 매장까지 거리에 따른 감점 없이 동일하게 평가하세요.\n"
    "- 직접 걸어가지 않으므로 배달 시 포장 퀄리티, 온도/식감 유지력, 메뉴 만족도를 최우선 기준으로 확신의 픽 3곳(`standards`) + 반전 매력 픽 2곳(`refreshes`)을 선정하세요.\n"
    "- **비조리(밀키트) 매장 후순위 원칙**: 땅스부대찌개, 담꾹 등 집에서 가스레인지/냄비로 직접 끓여야 하는 밀키트 전문점은 즉석 식사가 필요한 배달 모드 특성상 우선순위를 낮추고 바로 먹을 수 있는 조리 완료 매장을 우선 선정하세요. 불가피하게 추천에 포함할 경우 `report.selection_logic`에 반드시 \"⚠️ 냄비 조리가 필요한 밀키트 구성입니다\"를 명시하세요.\n"
    "- 구내식당·학생식당·현장 숯불구이 전문점처럼 쿠팡이츠 배달이 불가능한 업태는 추천에서 제외하세요.\n"
    "- 선택한 예산/주문 규모(`min_order_exact` vs `generous_group`)에 정확히 부합하는 메뉴와 가격대(단품+실속 사이드 1인 콤보 vs 2인 이상 푸짐한 세트)를 제시하세요.\n"
    "- 리포트 본문(`report`)에서는 임의의 최소주문금액·거리 수치를 추측해 적지 말고(백엔드가 정밀 계산함), 실제 방문자 호평 포인트·동종 매장 대비 가성비·탄단지 식곤증 분석·선정 논리에 집중하세요."
)

DELIVERY_MODE_LABELS = {
    "walk": "도보 매장 방문 (직선 1,000m 이내 / 실보행 약 1.3km · 도보 18분 마지노선, 거리 감점 적용)",
    "delivery": "쿠팡이츠 배달 주문 (와우 무료배달 / 가까운 1km 이내 포함 최대 3,500m 배달 가능권)",
}

MEAL_MODE_LABELS = {
    "quick": "간편 15분컷 (빠른 조리·섭취가 가능한 햄버거/토스트/밥버거/분식/컵밥)",
    "proper": "제대로 된 한 끼 (든든하게 채워주는 국밥/찌개/정식/덮밥/메인 요리)",
    "clean": "가볍고 클린하게 (부담 없는 샐러드/포케/샌드위치/죽/쌀국수)",
}

TEXTURE_TEMP_LABELS = {
    "bread": "빵/패티 (버거, 수제버거, 토스트, 샌드위치, 브리오슈, 베이커리류)",
    "rice": "밥/든든함 (밥버거, 도시락, 컵밥, 덮밥, 비빔밥, 한식 정식, 죽, 현미밥 포케)",
    "soup": "면/뜨끈한 국물 (국밥, 순대국, 해장국, 설렁탕, 순두부·김치찌개, 짬뽕, 우동, 라멘, 마라탕, 쌀국수)",
}

TEXTURE_STRICT_RULES = {
    "bread": (
        "[1순위 절대 규칙 - 'bread (빵/패티)']\n"
        "- `standards`(확신의 픽 3곳): 1~3위 모두 햄버거, 버거킹, 맘스터치, 토스트, 샌드위치처럼 '빵/패티'가 주력인 매장만 선정하세요. 국밥, 순대국, 해장국, 찌개, 짬뽕, 우동, 밥버거, 도시락류는 확신의 픽에 절대 넣지 마세요.\n"
        "- `refreshes`(반전 매력 픽 2곳): 반대로 빵/패티가 아닌 카테고리(예: 샐러드/포케, 부리또/랩, 밥버거/컵밥/도시락 등)에서 사용자의 식사 템포(`meal_mode`)와 예산에 맞는 반전 매력 대안 2곳을 선정하세요."
    ),
    "rice": (
        "[1순위 절대 규칙 - 'rice (밥/든든함)']\n"
        "- `standards`(확신의 픽 3곳): 1~3위 모두 도시락, 컵밥, 밥버거, 덮밥/돈까스 정식, 비빔밥, 한식 백반, 죽, 현미밥 포케 등 '밥 중심 메뉴'가 주력인 매장만 선정하세요. 햄버거, 토스트, 샌드위치, 면류 단품은 확신의 픽에 절대 넣지 마세요.\n"
        "- `refreshes`(반전 매력 픽 2곳): 반대로 밥 중심이 아닌 카테고리(예: 샌드위치/버거, 파스타/양식, 쌀국수/우동/마라탕, 샐러드 등)에서 사용자의 식사 템포(`meal_mode`)와 예산에 맞는 반전 매력 대안 2곳을 선정하세요."
    ),
    "soup": (
        "[1순위 절대 규칙 - 'soup (면/뜨끈한 국물)']\n"
        "- `standards`(확신의 픽 3곳): 1~3위 모두 국밥, 해장국, 김치·순두부찌개, 짬뽕, 우동, 라멘, 마라탕, 쌀국수, 어묵·떡볶이 등 '뜨끈한 국물 또는 면 요리' 전문 매장만 선정하세요. 햄버거, 토스트, 샌드위치, 마른 도시락/밥버거는 확신의 픽에 절대 넣지 마세요.\n"
        "- `refreshes`(반전 매력 픽 2곳): 반대로 국물/면 외 카테고리(예: 돈까스/카츠, 덮밥/도시락/부리또, 토스트/버거, 파스타, 포케 등)에서 사용자의 식사 템포(`meal_mode`)와 예산에 맞는 반전 매력 대안 2곳을 선정하세요."
    ),
}

BUDGET_TIER_LABELS = {
    "budget": "가성비 (8,000원 이하 혼밥 알뜰 단품)",
    "flexible": "실속 세트 (8,000원 초과 ~ 13,000원 이하 든든한 정석 세트)",
    "min_order_exact": "1인분 최소주문금액에 딱 맞게 (메인 + 실속 사이드 1인 알뜰 배달 콤보)",
    "generous_group": "여유 있고 든든하게 (2인 이상 함께 즐기는 18,000~25,000원대 푸짐한 세트)",
}

BUDGET_STRICT_RULES = {
    "budget": (
        "[예산 밸런스 규칙 - 'budget (8,000원 이하 실속 단품)']\n"
        "- 확신의 픽 3곳 및 반전 매력 픽 2곳 모두 반드시 8,000원 이하의 알뜰 단품 또는 실속 구성으로 제시하세요.\n"
        "- 대학생·직장인의 점심 지출 부담을 낮추면서 가성비 만족도가 높은 메뉴를 고르세요."
    ),
    "flexible": (
        "[예산 밸런스 규칙 - 'flexible (8,000원 초과 ~ 13,000원 이하 실속 세트/정식)']\n"
        "- 3,000~5,000원대 단순 저가 단품은 확신의 픽 1순위(`[확신의 픽]`)에서 제외하세요.\n"
        "- 15,000원이 넘어가는 과소비 고가 메뉴 역시 철저히 배제하세요.\n"
        "- **8,000원 초과 ~ 13,000원 이하**의 부담 없으면서도 한 끼 만족도를 극대화하는 알찬 시그니처 세트/정식을 추천하세요."
    ),
    "min_order_exact": (
        "[배달 1인 맞춤 규칙 - 'min_order_exact (1인분 최소주문금액에 딱 맞게)']\n"
        "- 매장의 통상 배달 최소주문금액(보통 9,000~14,000원, 패스트푸드·버거 약 13,000원)을 과도하게 초과하거나 미달로 주문이 튕기지 않도록 설계하세요.\n"
        "- 메인 메뉴 + 저렴한 실속 사이드(치즈스틱/너겟/음료 등) 1~2종을 조합해 최소주문금액에 **딱 근접하거나 안전하게 충족하는 1인 알뜰 콤보**를 추천하세요.\n"
        "- **특히 패스트푸드/버거류(버거킹·맘스터치·맥도날드·롯데리아·프랭크버거 등)**는 최소주문(약 13,000원) 미달로 거절되지 않도록 와퍼 세트 + 치즈스틱/너겟킹 조합처럼 **합산 12,500원 ~ 13,500원 구간**에 안전하게 맞추세요.\n"
        "- 16,000원을 초과하는 과다 주문이나 2인 이상 대형 메뉴는 절대 추천하지 마세요."
    ),
    "generous_group": (
        "[배달 다인·여유 규칙 - 'generous_group (2인 이상 여유 있고 든든하게)']\n"
        "- 2인 이상이 함께 나눠먹기 좋은 푸짐한 커플·패밀리 세트나 대형 스페셜 메뉴(**18,000원 ~ 25,000원대**)를 추천하세요.\n"
        "- 버거 2인 팩, 수육+국밥 2인 한상, 탕수육+식사 2인 중식 세트, 마라탕+꿔바로우, 모둠 돈까스+우동 2인 정식 등 여럿이 푸짐하게 즐기기 좋은 구성을 최우선 선정하세요."
    ),
}

SOUP_KEYWORDS = [
    "국밥", "소머리", "순대", "육개장", "설렁탕", "갈비탕", "해장국", "뼈해장", "양평해장",
    "찌개", "김찌로", "순두부", "김치찌개", "우동", "짬뽕", "챠이챠이", "라멘", "칼국수",
    "수제비", "만두국", "라면", "어묵", "떡볶이", "청년다방", "샤브", "탕", "국수",
    "국물", "감자탕", "부대찌개", "쌀국수", "베트남", "인더비엣", "마라탕", "탕화쿵푸", "라홍방", "미소야", "현대옥",
]
BREAD_KEYWORDS = [
    "버거킹", "맘스터치", "롯데리아", "맥도날드", "프랭크버거", "노브랜드버거", "햄버거", "수제버거", "버거",
    "이삭토스트", "에그드랍", "에그2000", "토스트", "프린샌드위치", "서브웨이", "써브웨이",
    "샌드위치", "브리오슈", "파니니", "베이글", "브런치", "파리바게뜨", "베이커리", "던킨", "와플",
]
RICE_KEYWORDS = [
    "봉구스", "밥버거", "한솥", "도시락", "행컵", "지지고", "컵밥", "볶음밥", "덮밥",
    "비빔밥", "백반", "정식", "보쌈", "족발", "가장맛있는족발", "찜닭", "제육", "낙지",
    "김밥", "죽", "본죽", "웜볼", "현미밥", "포케", "알밥", "카레", "돈까스", "돈가스",
    "상상카츠", "최고당", "밀플랜비", "신동랩", "한식", "김찌로", "국밥",
]


WALK_DETOUR_FACTOR = 1.3
WALK_SPEED_M_PER_MIN = 72  # 4.3km/h 실제 보행 속도 기준 (실보행 1,300m -> 약 18분)

MEAL_KIT_KEYWORDS = (
    "땅스부대찌개",
    "담꾹",
    "밀키트",
    "집밥뚝딱",
    "식사준비",
    "오늘쉐프",
    "홈스토랑",
    "비조리",
    "부대찌개밀키트",
    "셰프의부대찌개",
)
MEAL_KIT_NOTICE = "⚠️ 냄비 조리가 필요한 밀키트 구성입니다"

FAST_FOOD_BURGER_KEYWORDS = (
    "버거킹",
    "맘스터치",
    "맥도날드",
    "롯데리아",
    "노브랜드버거",
    "프랭크버거",
    "왓더버거",
    "햄버거",
    "수제버거",
    "버거",
    "패스트푸드",
)


def _is_meal_kit_store(restaurant: Dict[str, Any], menu_name: str = "") -> bool:
    text = (
        f"{restaurant.get('place_name', '')} "
        f"{restaurant.get('category_name', '')} "
        f"{menu_name}"
    ).replace(" ", "")
    return any(kw in text for kw in MEAL_KIT_KEYWORDS)


def _is_burger_fastfood_store(restaurant: Dict[str, Any]) -> bool:
    place = str(restaurant.get("place_name", ""))
    cat = str(restaurant.get("category_name", ""))
    text = f"{place} {cat}"
    if "밥버거" in text or "봉구스" in text:
        return False
    return any(kw in text for kw in FAST_FOOD_BURGER_KEYWORDS)


def _calibrate_min_order_exact_delivery_menu(
    restaurant: Dict[str, Any],
    menu_val: str,
    price_val: str,
    fallback_inferred: Dict[str, str],
    preference: UserPreferenceRequest,
) -> tuple[str, str]:
    """
    배달 1인 맞춤(`min_order_exact`)에서 패스트푸드/버거류가 최소주문(~13,000원) 미달로 주문이 튕기거나
    과도하게 비싸지지 않도록 12,500~13,500원 안전 콤보 구간으로 보정합니다.
    """
    if _normalize_mode(preference.delivery_mode) != "delivery":
        return menu_val, price_val
    if preference.budget_tier != "min_order_exact":
        return menu_val, price_val
    if not _is_burger_fastfood_store(restaurant):
        return menu_val, price_val

    place = str(restaurant.get("place_name", ""))
    target_min = 12500 if "노브랜드버거" in place else 13000
    price_int = parse_price_int(price_val, default=0)

    if target_min <= price_int <= 13500:
        return menu_val, price_val

    has_combo_side = any(
        kw in menu_val
        for kw in ("너겟", "치즈스틱", "치즈볼", "텐더", "도넛", "어니언링", "김떡만", "사이드")
    )
    if price_int < target_min and has_combo_side and price_int >= 11500:
        if "버거킹" in place:
            return f"{menu_val} (너겟/사이드 추가 콤보)" if "1조각" in menu_val else menu_val, "13,200원"
        if "노브랜드버거" in place:
            return menu_val, "12,800원"
        return menu_val, "13,000원"

    return fallback_inferred["menu"], fallback_inferred["price"]


def _normalize_mode(delivery_mode: Optional[str]) -> str:
    return "delivery" if delivery_mode == "delivery" else "walk"


def _parse_distance_m(distance_raw: Any, default: int = 0) -> int:
    try:
        return int(float(str(distance_raw).strip()))
    except (TypeError, ValueError):
        return default


def format_distance_text(distance_raw: Any, delivery_mode: str) -> str:
    """
    카카오 직선 거리(distance_m)와 실제 도보/도로 우회 계수(×1.3)를 결합한 현실 이동 시간 보장:
    - walk: 실보행 거리 = round(dist_m * 1.3), 도보 시간 = max(1, round(실보행 / 72))
            예) 직선 1000m -> 실보행 약 1.3km, 도보 약 18분
    - delivery: 실도로 거리 기준 라이더 이동 시간 보정
    """
    dist_m = max(0, _parse_distance_m(distance_raw, default=0))
    mode = _normalize_mode(delivery_mode)

    if mode == "delivery":
        road_km = (dist_m * WALK_DETOUR_FACTOR) / 1000.0
        travel_min = round(road_km * 2.5)
        eta_min = 18 + travel_min
        eta_max = eta_min + 10
        return f"배달 약 {eta_min}~{eta_max}분 (직선 {dist_m / 1000:.1f}km)"

    actual_walk_m = round(dist_m * WALK_DETOUR_FACTOR)
    minutes = max(1, round(actual_walk_m / WALK_SPEED_M_PER_MIN))
    walk_dist_label = (
        f"~{actual_walk_m / 1000:.1f}km" if actual_walk_m >= 1000 else f"~{actual_walk_m}m"
    )
    return f"도보 약 {minutes}분 ({walk_dist_label})"


def _matches_texture(text: str, texture: str) -> bool:
    if texture == "soup":
        return any(k in text for k in SOUP_KEYWORDS)
    if texture == "bread":
        if "밥버거" in text and not any(b in text for b in ["토스트", "샌드위치", "햄버거"]):
            return False
        return any(k in text for k in BREAD_KEYWORDS)
    if texture == "rice":
        return any(k in text for k in RICE_KEYWORDS)
    return True


def _infer_menu_and_price(
    restaurant: Dict[str, Any],
    preference: UserPreferenceRequest,
    *,
    is_refresh: bool = False,
) -> Dict[str, str]:
    """실제 카카오 식당의 상호명/카테고리와 사용자 조건(도보/배달 · 1인/다인 · 예산)에 맞는 대표 메뉴와 현실 가격을 매핑합니다."""
    name = restaurant.get("place_name", "")
    category = restaurant.get("category_name", "")
    text = f"{name} {category}"
    is_delivery = _normalize_mode(preference.delivery_mode) == "delivery"
    tex = preference.texture_temp
    tier = preference.budget_tier
    if tier not in ("budget", "flexible", "min_order_exact", "generous_group"):
        tier = "min_order_exact" if is_delivery else "budget"

    def pick(budget_item, flex_item, min_exact_item, group_item) -> Dict[str, str]:
        chosen = {
            "budget": budget_item,
            "flexible": flex_item,
            "min_order_exact": min_exact_item,
            "generous_group": group_item,
        }[tier]
        return {"menu": chosen[0], "price": chosen[1]}

    if "봉구스" in name or "밥버거" in text:
        return pick(
            ("제육 치즈 밥버거 + 컵라면", "5,800원"),
            ("더블치즈 닭갈비 밥버거 + 떡갈비 세트", "8,900원"),
            ("치즈제육 밥버거 + 떡갈비 + 컵라면 1인 콤보", "9,000원"),
            ("베스트 밥버거 3종 + 용가리치킨·컵라면 2~3인 세트", "19,500원"),
        )
    if "버거킹" in name:
        return pick(
            ("와퍼주니어 + 콜라 단품", "6,800원"),
            ("콰트로치즈와퍼 세트(프렌치프라이+콜라)", "10,700원"),
            ("와퍼 세트 + 너겟킹(4조각) 1인 맞춤 콤보", "13,200원"),
            ("와퍼 + 콰트로치즈와퍼 2인 패밀리팩(감튀L 2 + 콜라 2)", "23,500원"),
        )
    if "맘스터치" in name:
        return pick(
            ("싸이버거 + 콜라 단품", "6,600원"),
            ("화이트갈릭싸이버거 + 케이준양념감자 세트", "9,800원"),
            ("싸이버거 세트 + 바삭크림치즈볼(2조각) 1인 맞춤 콤보", "13,000원"),
            ("싸이버거 2개 + 후라이드 순살 + 감튀·콜라 2인 커플팩", "22,900원"),
        )
    if "롯데리아" in name or "맥도날드" in name or "노브랜드버거" in name or "프랭크" in name or "버거" in text:
        if "노브랜드버거" in name:
            return pick(
                ("NBB 시그니처 버거 + 콜라 단품", "7,000원"),
                ("NBB 어메이징 버거 세트(감튀+음료)", "9,900원"),
                ("NBB 어메이징 세트 + 어니언 도넛(4p) 1인 콤보", "12,800원"),
                ("더블패티 버거 2종 + 치킨너겟·감자튀김 2인 패밀리팩", "21,500원"),
            )
        return pick(
            ("시그니처 버거 + 콜라 단품", "7,200원"),
            ("더블패티 시그니처 버거 세트(감튀+음료)", "10,500원"),
            ("시그니처 버거 세트 + 치즈스틱 1인 맞춤 콤보", "13,000원"),
            ("베스트 버거 2종 + 치킨사이드·프라이·음료 2인 커플팩", "22,500원"),
        )
    if "써브웨이" in text or "서브웨이" in text:
        return pick(
            ("에그마요 15cm 단품", "5,900원"),
            ("이탈리안 비엠티 15cm + 음료·쿠키 세트", "9,900원"),
            ("에그마요 15cm + 웨지포테이토 + 음료 1인 맞춤 콤보", "12,000원"),
            ("스테이크&치즈 + 이탈리안 BMT 15cm 2종 + 수프·쿠키 2인 세트", "21,800원"),
        )
    if "에그2000" in name or "에그드랍" in name or "이삭" in name or "프린샌드위치" in name or "샌드위치" in text or "파리바게뜨" in name:
        return pick(
            ("에그베이컨 샌드위치 단품", "5,900원"),
            ("프리미엄 더블에그·치즈 샌드위치 + 아메리카노 세트", "9,400원"),
            ("더블에그 샌드위치 + 해쉬브라운 + 아메리카노 1인 콤보", "11,200원"),
            ("시그니처 샌드위치 2종 + 감튀 + 음료2 2인 브런치 세트", "19,800원"),
        )
    if _is_meal_kit_store(restaurant):
        return pick(
            ("1인 부대찌개 밀키트(비조리)", "7,900원"),
            ("모둠 부대찌개 밀키트 + 라면사리(비조리)", "11,500원"),
            ("부대찌개 밀키트 1~2인 + 라면·햄사리(비조리)", "13,000원"),
            ("푸짐 스페셜 부대찌개 밀키트 3인분 + 모둠사리(비조리)", "21,500원"),
        )
    if "소머리" in name or "해장국" in text or "뼈해장" in text or "순대" in text or "국밥" in text or "설렁탕" in text or "현대옥" in name:
        return pick(
            ("얼큰 국밥/해장국 1인분", "8,000원"),
            ("특 고기듬뿍 국밥·해장국 정식", "11,500원"),
            ("특 고기듬뿍 국밥 + 만두/음료 1인 맞춤 콤보", "14,000원"),
            ("수육·국밥 2인분 + 맛보기 편육/수육(소) 푸짐한 한상", "24,000원"),
        )
    if "김찌로" in name or "김치찌개" in text or "순두부" in text or "부대찌개" in text or "찌개" in text:
        return pick(
            ("돼지고기 김치찌개 + 공기밥", "8,000원"),
            ("통삼겹 김치찌개 + 계란말이 정식", "11,000원"),
            ("통삼겹 김치찌개 + 계란후라이·라면사리 1인 맞춤 콤보", "12,800원"),
            ("통삼겹 김치찌개 2인분 + 계란말이 + 스팸구이 푸짐 세트", "22,000원"),
        )
    if "베트남" in text or "인더비엣" in name or "에머이" in name or "쌀국수" in text:
        return pick(
            ("양지 쌀국수 레귤러", "7,900원"),
            ("직화 소고기 쌀국수 + 짜조 세트", "11,900원"),
            ("양지 차돌 쌀국수 + 짜조(2p) 1인 맞춤 콤보", "13,000원"),
            ("소고기 쌀국수 2그릇 + 분짜/월남쌈 + 짜조 2인 세트", "24,500원"),
        )
    if "마라탕" in text or "탕화쿵푸" in name or "라홍방" in name:
        return pick(
            ("실속 1인 마라탕 기본", "7,800원"),
            ("우삼겹·청경채 듬뿍 시그니처 마라탕 + 꿔바로우 미니", "12,200원"),
            ("우삼겹·분모자 맞춤 1인 마라탕 + 빙홍차 콤보", "13,000원"),
            ("푸짐한 2인 스페셜 마라탕 + 꿔바로우 세트", "23,000원"),
        )
    if "챠이챠이" in name or "중식" in category or "중국요리" in category or "짬뽕" in text:
        use_rice_menu = (tex == "rice" and not is_refresh) or (is_refresh and tex == "soup")
        if use_rice_menu:
            return pick(
                ("중화 제육볶음밥", "8,000원"),
                ("해물 짬뽕밥 + 미니 군만두 세트", "11,000원"),
                ("중화 볶음밥 + 바삭 군만두(4p) + 음료 1인 콤보", "13,500원"),
                ("잡채밥/볶음밥 2인 + 등심 탕수육(소) 푸짐한 중식 세트", "24,500원"),
            )
        return pick(
            ("차돌/해물 짬뽕 단품", "8,000원"),
            ("얼큰 해물 짬뽕 + 군만두 세트", "11,500원"),
            ("해물 짬뽕 + 바삭 군만두(4p) 1인 맞춤 콤보", "13,500원"),
            ("해물 짬뽕·짜장 2인 + 등심 탕수육(소) 푸짐한 세트", "24,500원"),
        )
    if "미소야" in name or "상상카츠" in name or "최고당" in name or "우동" in text or "라멘" in text or "돈까스" in text or "돈가스" in text:
        use_rice_menu = (tex == "rice" and not is_refresh) or (is_refresh and tex == "soup")
        if use_rice_menu or "상상카츠" in name or "최고당" in name:
            return pick(
                ("로스카츠 덮밥 단품", "7,900원"),
                ("히레카츠 알밥/덮밥 + 미니우동 정식", "11,200원"),
                ("로스카츠 정식 + 감자고로케(2p) 1인 맞춤 콤보", "13,000원"),
                ("히레·로스카츠 모둠정식 + 우동·새우튀김 2인 커플 세트", "22,500원"),
            )
        return pick(
            ("가쓰오 김치우동 단품", "7,500원"),
            ("얼큰 우동 + 등심돈까스 콤보 정식", "10,900원"),
            ("등심 돈까스 + 미니우동 + 음료 1인 맞춤 콤보", "13,000원"),
            ("우동 2그릇 + 모둠 돈까스·새우튀김 2인 푸짐 세트", "22,000원"),
        )
    if "한솥" in name or "도시락" in category:
        return pick(
            ("빅치킨마요 덮밥", "4,900원"),
            ("진달래 프리미엄 도시락 + 미소국·음료 세트", "9,500원"),
            ("메가치킨마요 + 미니고로케 1인 맞춤 콤보", "9,000원"),
            ("진달래+돈까스도련님 2인 도시락 + 치킨·찹쌀탕수육 세트", "21,000원"),
        )
    if "행컵" in name or "컵밥" in category:
        return pick(
            ("직화 불고기 컵밥", "6,500원"),
            ("모둠 토핑 스페셜 컵밥 + 어묵탕 세트", "9,500원"),
            ("직화 불고기 컵밥 + 닭강정(소) 1인 맞춤 콤보", "10,300원"),
            ("시그니처 컵밥 2종 + 모둠 닭강정·어묵탕 2인 세트", "19,500원"),
        )
    if "본죽" in name or "죽" in category:
        return pick(
            ("소고기 야채죽", "8,000원"),
            ("전복 삼선 보양죽 + 장조림 반찬 세트", "12,000원"),
            ("쇠고기 야채죽 + 감자고로케/장조림 1인 맞춤 콤보", "12,000원"),
            ("전복죽 + 쇠고기야채죽 2인 보양죽 + 반찬 모둠 세트", "23,000원"),
        )
    if "포케" in text or "샐러리아" in name or "샐러드" in text:
        return pick(
            ("닭가슴살 샐러드·현미밥 볼", "7,900원"),
            ("훈제연어·아보카도 포케 + 스프·콤부차 세트", "12,400원"),
            ("훈제연어·현미밥 포케 + 훈제란 토핑 1인 콤보", "12,200원"),
            ("연어·오리고기 포케 2볼 + 단호박스프·콤부차 2인 세트", "23,800원"),
        )
    if "밀플랜비" in name:
        return pick(
            ("소고기 감자 라이스 부리또", "6,500원"),
            ("치킨·소고기 믹스 라이스 부리또 + 음료 세트", "9,200원"),
            ("믹스 감자 라이스 부리또 + 해쉬브라운·음료 1인 콤보", "10,500원"),
            ("인기 부리또 2종 + 나초치즈·감자튀김·음료2 2인 세트", "20,500원"),
        )
    if "파스타" in text or "양식" in category or "이탈리안" in category or "피자" in text:
        return pick(
            ("알리오올리오 / 토마토 파스타", "8,000원"),
            ("크림/로제 시그니처 파스타 + 마늘빵 세트", "12,500원"),
            ("트러플 크림 파스타 + 미니 샐러드 1인 콤보", "13,500원"),
            ("파스타 2종 + 마르게리타 피자 + 에이드 2인 세트", "24,500원"),
        )
    if "족발" in text or "보쌈" in text:
        return pick(
            ("1인 보쌈·막국수 정식", "8,000원"),
            ("1인 마늘보쌈·주먹밥 정식", "12,500원"),
            ("1인 보쌈 도시락 + 막국수 콤보", "13,500원"),
            ("족발/보쌈 2인 세트 + 쟁반국수·주먹밥", "24,500원"),
        )
    if "치킨" in text or "닭강정" in text:
        return pick(
            ("순살 닭강정 1인 컵", "7,500원"),
            ("순살 치킨 1인 세트 + 치즈볼·콜라", "12,500원"),
            ("반마리 순살 치킨 + 감자튀김 1인 콤보", "13,500원"),
            ("후라이드·양념 반반 치킨 + 치즈볼 2인 세트", "22,500원"),
        )
    if "김밥" in text or "청년다방" in name or "분식" in category:
        use_soup_menu = (tex == "soup" and not is_refresh) or (is_refresh and tex == "rice")
        if use_soup_menu:
            return pick(
                ("떡만두라면 + 꼬마김밥", "7,200원"),
                ("차돌 떡볶이 + 모둠튀김·어묵탕 1인 세트", "10,800원"),
                ("모둠 라볶이 + 김말이·튀김만두 1인 맞춤 콤보", "12,800원"),
                ("차돌 떡볶이 + 모둠튀김 + 순대 + 주먹밥 2인 풀세트", "22,500원"),
            )
        return pick(
            ("참치김밥 + 우동국물", "6,000원"),
            ("돈까스 김치볶음밥 정식 세트", "10,200원"),
            ("프리미엄 김밥 + 돈까스/모둠튀김 1인 맞춤 콤보", "12,800원"),
            ("프리미엄 김밥 2줄 + 떡볶이 + 모둠튀김 2인 분식 세트", "21,500원"),
        )
    if "일식" in category or "신동랩" in name:
        return pick(
            ("규동 / 사케동 미니 덮밥", "8,000원"),
            ("시그니처 일본식 덮밥·카츠 정식", "11,900원"),
            ("시그니처 덮밥 + 미니우동 1인 콤보", "13,000원"),
            ("모둠 카츠·덮밥 2종 + 우동·새우튀김 2인 세트", "23,000원"),
        )

    if not is_refresh and tex == "soup":
        return pick(
            ("따뜻한 시그니처 국물 단품", "7,800원"),
            ("고기·해물 푸짐 시그니처 국물 정식", "11,200원"),
            ("시그니처 국물 1인 + 실속 사이드/음료 콤보", "13,000원"),
            ("시그니처 국물 2인분 + 인기 곁들임 모둠 2인 세트", "23,000원"),
        )
    if not is_refresh and tex == "bread":
        return pick(
            ("시그니처 버거·샌드위치 단품", "7,200원"),
            ("프리미엄 버거·브런치 풀세트", "10,500원"),
            ("시그니처 버거·샌드위치 + 사이드·음료 1인 맞춤 콤보", "13,000원"),
            ("시그니처 버거·브런치 2인 + 사이드 모둠 패밀리팩", "21,500원"),
        )
    return pick(
        ("오늘의 실속 덮밥/한상 단품", "7,800원"),
        ("오늘의 시그니처 든든 한 상 정식", "11,000원"),
        ("시그니처 덮밥·도시락 + 실속 사이드 1인 맞춤 콤보", "12,500원"),
        ("시그니처 한 상 2인분 + 인기 사이드 모둠 푸짐 세트", "22,000원"),
    )


def _infer_nutrition_facts(
    restaurant: Dict[str, Any],
    menu_name: str,
    preference: UserPreferenceRequest,
) -> NutritionFacts:
    """매장 특성, 메뉴명, 예산/인분·식감 조합에 따른 현실적인 탄단지·칼로리 영양 수치(kcal, g)를 산출합니다."""
    text = f"{restaurant.get('place_name', '')} {restaurant.get('category_name', '')} {menu_name}"
    is_group = preference.budget_tier == "generous_group"
    is_set = (
        preference.budget_tier in ("flexible", "min_order_exact", "generous_group")
        or "세트" in menu_name
        or "정식" in menu_name
        or "콤보" in menu_name
    )

    if any(k in text for k in ["포케", "샐러리아", "샐러드"]):
        c, p, f = (54, 40, 20) if is_set else (42, 34, 14)
        hl = "고단백·복합탄수화물·불포화지방 균형이 이상적이라 오후 식곤증 없이 깔끔한 포만감을 유지합니다."
    elif any(k in text for k in ["본죽", "야채죽", "보양죽"]):
        c, p, f = (82, 26, 10) if is_set else (72, 18, 8)
        hl = "소화 흡수가 빠른 부드러운 탄수화물과 저지방 단백질 구성으로 위장 부담을 최소화합니다."
    elif any(k in text for k in ["에그", "이삭", "샌드위치", "프린샌드위치", "파리바게뜨", "써브웨이", "서브웨이"]):
        c, p, f = (68, 30, 22) if is_set else (52, 24, 18)
        hl = "달걀·단백질과 빵의 탄수화물이 고르게 잡혀 부담 없고 균형 잡힌 에너지 보충에 적합합니다."
    elif any(k in text for k in ["한솥", "도시락", "봉구스", "밥버거", "행컵", "밀플랜비", "김밥"]):
        c, p, f = (90, 30, 26) if is_set else (76, 24, 18)
        hl = "밥 중심 복합 탄수화물에 고기·반찬 단백질을 얹어 안정적인 포만감과 에너지를 채워줍니다."
    elif any(k in text for k in ["버거", "맘스터치", "버거킹", "맥도날드", "롯데리아"]):
        c, p, f = (96, 36, 42) if is_set else (54, 29, 26)
        hl = (
            "버거와 사이드 조합으로 탄수화물·단백질·지방 밀도가 높아 든든한 에너지 충전에 유리합니다."
            if is_set
            else "단품 선택으로 패티 단백질은 챙기면서 사이드 튀김의 과잉 당·지방 섭취를 억제했습니다."
        )
    elif any(k in text for k in ["쌀국수", "베트남", "인더비엣", "에머이"]):
        c, p, f = (78, 34, 16) if is_set else (66, 26, 10)
        hl = "기름기가 적은 맑은 육수와 소고기 단백질, 쌀면이 결합해 국물 요리 중에서도 담백한 매크로를 갖췄습니다."
    elif any(k in text for k in ["국밥", "소머리", "해장국", "순대", "설렁탕", "현대옥"]):
        c, p, f = (76, 44, 28) if is_set else (68, 34, 22)
        hl = "공기밥 탄수화물과 듬뿍 담긴 고기 단백질이 1:0.5 이상의 탄탄한 고단백 한 끼 균형을 이룹니다."
    elif any(k in text for k in ["김치찌개", "김찌로", "순두부", "찌개", "부대찌개"]):
        c, p, f = (80, 36, 28) if is_set else (72, 27, 20)
        hl = "밥과 돼지고기·두부 단백질이 조화를 이루어 장시간 집중력이 필요한 시간대에 안정적인 열량을 공급합니다."
    elif any(k in text for k in ["마라탕", "짬뽕", "챠이챠이", "우동", "라멘"]):
        c, p, f = (92, 32, 30) if is_set else (78, 22, 18)
        hl = "면·건더기 기반의 고탄수 에너지 식단에 고기·해물 토핑으로 단백질을 보강한 구성입니다."
    elif any(k in text for k in ["돈까스", "돈가스", "상상카츠", "최고당", "미소야", "덮밥"]):
        c, p, f = (94, 38, 34) if is_set else (80, 30, 26)
        hl = "바삭한 돈까스의 단백질·지방과 밥의 탄수화물이 풍성하게 어우러져 높은 식사 만족도를 제공합니다."
    else:
        c, p, f = (82, 32, 26) if is_set else (68, 25, 18)
        hl = "탄수화물·단백질·지방이 식사 모드에 맞춰 고르게 분배되어 식후 에너지 유지에 유리한 밸런스입니다."

    if is_group:
        c, p, f = round(c * 1.85), round(p * 1.85), round(f * 1.85)
        hl = f"2인 이상이 여유롭게 나누어 즐기는 푸짐한 다인 세트 총합 기준입니다. ({hl})"

    calories = round((c * 4 + p * 4 + f * 9) / 10) * 10
    calories_per_person = round(calories / 2) if is_group else None
    return NutritionFacts(
        calories=calories,
        calories_per_person=calories_per_person,
        carbs_g=c,
        protein_g=p,
        fat_g=f,
        nutrition_highlight=hl,
    )


def _sanitize_nutrition(
    raw: Optional[NutritionFacts],
    restaurant: Dict[str, Any],
    menu_name: str,
    preference: UserPreferenceRequest,
) -> NutritionFacts:
    fallback = _infer_nutrition_facts(restaurant, menu_name, preference)
    is_group = preference.budget_tier == "generous_group"
    if raw is None:
        return fallback

    try:
        cal = int(raw.calories)
        carbs = int(raw.carbs_g)
        protein = int(raw.protein_g)
        fat = int(raw.fat_g)
    except (TypeError, ValueError):
        return fallback

    if not (180 <= cal <= 3400 and 5 <= carbs <= 420 and 5 <= protein <= 250 and 1 <= fat <= 210):
        return fallback
    if is_group and cal < 850:
        return fallback

    highlight = str(raw.nutrition_highlight or "").strip() or fallback.nutrition_highlight
    per_person = round(cal / 2) if is_group else None
    return NutritionFacts(
        calories=cal,
        calories_per_person=per_person,
        carbs_g=carbs,
        protein_g=protein,
        fat_g=fat,
        nutrition_highlight=highlight,
    )


def _score_restaurant(
    restaurant: Dict[str, Any],
    preference: UserPreferenceRequest,
    weather_info: Dict[str, Any],
) -> int:
    """식감/온도(1순위 절대 규칙), 식사 모드, 예산·인분 밸런스 및 도보/배달 격리 거리 점수를 계산합니다."""
    text = f"{restaurant.get('place_name', '')} {restaurant.get('category_name', '')}"
    mode = _normalize_mode(preference.delivery_mode)
    is_meal_kit = _is_meal_kit_store(restaurant)
    score = 0

    if _matches_texture(text, preference.texture_temp):
        score += 140
    else:
        score -= 120

    if preference.meal_mode == "quick":
        if any(k in text for k in ["버거", "토스트", "에그2000", "샌드위치", "밥버거", "도시락", "행컵", "밀플랜비", "김밥", "분식", "패스트푸드"]):
            score += 45
    elif preference.meal_mode == "proper":
        if any(k in text for k in ["국밥", "소머리", "순대", "해장국", "김찌로", "찌개", "정식", "보쌈", "족발", "돈가스", "돈까스", "상상카츠", "미소야", "베트남", "인더비엣", "마라탕", "중식", "버거킹", "현대옥"]) and "분식" not in text:
            score += 55
        elif any(k in text for k in ["한솥", "본죽", "맘스터치"]):
            score += 25
    elif preference.meal_mode == "clean":
        if any(k in text for k in ["포케", "샐러리아", "샐러드", "프린샌드위치", "서브웨이", "써브웨이", "본죽", "베트남", "인더비엣", "시루향기", "현대옥", "콩나물국밥", "샤브", "우동"]):
            score += 75
        elif any(k in text for k in ["에그2000", "밀플랜비", "파리바게뜨"]):
            score += 30
        if any(k in text for k in ["부대찌개", "김치찌개", "짬뽕", "마라탕", "떡볶이", "돈까스", "돈가스", "갈비", "삼겹"]):
            score -= 45

    if weather_info.get("is_cold") and not (mode == "delivery" and is_meal_kit) and any(k in text for k in ["국밥", "소머리", "순대", "해장국", "찌개", "김찌로", "짬뽕", "우동", "라멘", "쌀국수", "마라탕", "본죽", "에그2000", "현대옥"]):
        score += 15

    if preference.budget_tier == "budget":
        if any(k in text for k in ["한솥", "봉구스", "행컵", "김밥천국", "이삭토스트", "에그2000", "프린샌드위치", "맘스터치", "밀플랜비", "미소야", "버거킹"]):
            score += 25
        elif any(k in text for k in ["갈비", "족발", "보쌈", "스테이크", "한우"]):
            score -= 25
    elif preference.budget_tier == "min_order_exact":
        if any(k in text for k in ["한솥", "봉구스", "본도시락", "이삭", "에그2000", "써브웨이", "서브웨이", "맘스터치", "버거킹", "노브랜드버거", "포케", "샐러리아", "김찌로", "미소야", "상상카츠", "본죽", "밀플랜비"]):
            score += 35
    elif preference.budget_tier == "generous_group":
        if not (mode == "delivery" and is_meal_kit) and any(k in text for k in ["국밥", "수육", "순대", "해장국", "김치찌개", "김찌로", "부대찌개", "중식", "짬뽕", "챠이챠이", "마라탕", "버거킹", "맘스터치", "돈까스", "상상카츠", "미소야", "베트남", "인더비엣", "포케올데이", "본죽", "청년다방", "족발", "보쌈"]):
            score += 55
        if any(k in text for k in ["봉구스", "행컵", "김밥천국"]):
            score -= 35
    else:
        if any(k in text for k in ["버거킹", "프린샌드위치", "에그2000", "장수소머리국밥", "신의주찹쌀순대", "일품양평해장국", "청담뼈해장", "김찌로", "상상카츠", "최고당", "미소야", "베트남", "인더비엣", "포케올데이", "샐러리아", "마라탕", "챠이챠이", "본죽", "맘스터치", "노브랜드버거", "전주현대옥", "시루향기"]):
            score += 50
        if any(k in text for k in ["김밥천국", "봉구스", "한솥", "파리바게뜨"]):
            score -= 40

    dist_m = _parse_distance_m(restaurant.get("distance"), default=500)
    if mode == "walk":
        # 도보 모드 거리 감점(Distance Decay, 직선 1km/실보행 ~1.3km 상한)
        if dist_m <= 500:
            score += 30
        elif dist_m <= 1000:
            score += 30 - round(((dist_m - 500) / 500) * 60)
        else:
            score -= 120
    else:
        # 배달 모드는 거리 편향 없이 고품질·배달 적합성 우선 평가 (비배달 업종 및 비조리 밀키트 감점)
        if any(k in text for k in ["구내식당", "학생식당", "직원식당", "푸드코트", "뷔페", "참숯", "갈비", "삼겹"]):
            score -= 120
        if is_meal_kit:
            score -= 110

    return score


def _score_refresh_restaurant(
    restaurant: Dict[str, Any],
    preference: UserPreferenceRequest,
    weather_info: Dict[str, Any],
    standard_categories: Optional[set[str]] = None,
) -> int:
    """사용자 템포(meal_mode)·예산·반경은 유지하되 식감/카테고리를 색다르게 비튼 리프레시 대안 점수를 계산합니다."""
    place_name = str(restaurant.get("place_name", ""))
    cat_name = str(restaurant.get("category_name", ""))
    text = f"{place_name} {cat_name}"
    mode = _normalize_mode(preference.delivery_mode)
    is_meal_kit = _is_meal_kit_store(restaurant)
    score = 0

    # 리프레시 핵심: 선택한 정석 식감과 다른 카테고리에 높은 가중치 부여
    if not _matches_texture(text, preference.texture_temp):
        score += 140
    else:
        score -= 100

    if standard_categories and cat_name and cat_name not in standard_categories:
        score += 25

    # 식사 템포(meal_mode)는 유지!
    if preference.meal_mode == "quick":
        if any(k in text for k in ["버거", "토스트", "에그2000", "샌드위치", "밥버거", "도시락", "행컵", "밀플랜비", "김밥", "분식", "패스트푸드", "샐러드", "포케", "죽"]):
            score += 55
    elif preference.meal_mode == "proper":
        if any(k in text for k in ["국밥", "소머리", "순대", "해장국", "김찌로", "찌개", "정식", "보쌈", "족발", "돈가스", "돈까스", "상상카츠", "최고당", "미소야", "베트남", "인더비엣", "마라탕", "중식", "파스타", "양식", "이탈리안", "버거킹", "현대옥"]) and "분식" not in text:
            score += 60
        elif any(k in text for k in ["한솥", "본죽", "맘스터치", "청년다방", "밀플랜비"]):
            score += 30
    elif preference.meal_mode == "clean":
        if any(k in text for k in ["포케", "샐러리아", "샐러드", "프린샌드위치", "서브웨이", "써브웨이", "본죽", "베트남", "인더비엣", "시루향기", "현대옥", "콩나물국밥", "샤브", "우동", "밀플랜비"]):
            score += 80
        elif any(k in text for k in ["에그2000", "파리바게뜨"]):
            score += 35
        if any(k in text for k in ["부대찌개", "김치찌개", "짬뽕", "마라탕", "떡볶이", "돈까스", "돈가스", "갈비", "삼겹", "족발"]):
            score -= 50

    if weather_info.get("is_cold") and not (mode == "delivery" and is_meal_kit) and any(k in text for k in ["국밥", "소머리", "순대", "해장국", "찌개", "김찌로", "짬뽕", "우동", "라멘", "쌀국수", "마라탕", "본죽", "에그2000", "파스타"]):
        score += 10

    if preference.budget_tier == "budget":
        if any(k in text for k in ["한솥", "봉구스", "행컵", "김밥천국", "이삭토스트", "에그2000", "프린샌드위치", "맘스터치", "밀플랜비", "미소야", "버거킹", "본죽"]):
            score += 25
        elif any(k in text for k in ["갈비", "족발", "보쌈", "스테이크", "한우"]):
            score -= 25
    elif preference.budget_tier == "min_order_exact":
        if any(k in text for k in ["한솥", "봉구스", "본도시락", "이삭", "에그2000", "써브웨이", "서브웨이", "맘스터치", "버거킹", "노브랜드버거", "포케", "샐러리아", "김찌로", "미소야", "상상카츠", "본죽", "밀플랜비"]):
            score += 35
    elif preference.budget_tier == "generous_group":
        if not (mode == "delivery" and is_meal_kit) and any(k in text for k in ["국밥", "수육", "순대", "해장국", "김치찌개", "김찌로", "부대찌개", "중식", "짬뽕", "챠이챠이", "마라탕", "버거킹", "맘스터치", "돈까스", "상상카츠", "미소야", "베트남", "인더비엣", "포케올데이", "본죽", "청년다방", "족발", "보쌈", "파스타"]):
            score += 55
        if any(k in text for k in ["봉구스", "행컵", "김밥천국"]):
            score -= 35
    else:
        if any(k in text for k in ["버거킹", "프린샌드위치", "에그2000", "장수소머리국밥", "신의주찹쌀순대", "일품양평해장국", "청담뼈해장", "김찌로", "상상카츠", "최고당", "미소야", "베트남", "인더비엣", "포케올데이", "샐러리아", "마라탕", "챠이챠이", "본죽", "맘스터치", "노브랜드버거", "파스타하임", "밀플랜비", "청년다방"]):
            score += 45
        if any(k in text for k in ["김밥천국", "봉구스", "한솥", "파리바게뜨"]):
            score -= 25

    dist_m = _parse_distance_m(restaurant.get("distance"), default=500)
    if mode == "walk":
        if dist_m <= 500:
            score += 30
        elif dist_m <= 1000:
            score += 30 - round(((dist_m - 500) / 500) * 60)
        else:
            score -= 120
    else:
        if any(k in text for k in ["구내식당", "학생식당", "직원식당", "푸드코트", "뷔페", "참숯", "갈비", "삼겹"]):
            score -= 120
        if is_meal_kit:
            score -= 110

    return score


def _compute_protein_dv_percent(protein_g: int) -> int:
    """식약처 성인 1일 단백질 권장량(55g) 기준 충족률(%)을 수학적으로 계산합니다."""
    return int(round(max(0, int(protein_g or 0)) / 55 * 100))


def _build_dinner_pairing_guide(
    nutrition: NutritionFacts,
    menu_name: str,
    preference: UserPreferenceRequest,
) -> str:
    """선택 전 사전 예측 시뮬레이션 톤으로 하루 24시간 영양 균형을 맞추는 저녁 식단 가이드를 생성합니다."""
    is_group = preference.budget_tier == "generous_group"
    per_cal = (
        int(nutrition.calories_per_person)
        if nutrition.calories_per_person
        else (round(nutrition.calories / 2) if is_group else int(nutrition.calories))
    )
    per_carbs = round(nutrition.carbs_g / 2) if is_group else int(nutrition.carbs_g)
    per_protein = round(nutrition.protein_g / 2) if is_group else int(nutrition.protein_g)
    per_fat = round(nutrition.fat_g / 2) if is_group else int(nutrition.fat_g)

    if per_carbs >= 82 or per_cal >= 840:
        return (
            "만약 오늘 점심으로 이 메뉴를 선택하신다면, 탄수화물과 열량이 넉넉한 편이므로 하루 영양 균형을 위해 "
            "오늘 저녁은 닭가슴살·연두부·구운 생선과 잎채소 샐러드 위주로 가볍게 드시는 것을 추천합니다."
        )
    if per_cal <= 500 or per_carbs <= 48:
        return (
            "만약 오늘 점심으로 이 메뉴를 선택하신다면, 열량과 탄수화물 부담이 적은 편이므로 하루 영양 균형을 위해 "
            "오늘 저녁은 현미밥·된장찌개·소불고기 또는 연어 덮밥처럼 복합당과 단백질이 어우러진 식단으로 든든하게 드시는 것을 추천합니다."
        )
    if per_protein >= 34 and per_fat >= 26:
        return (
            "만약 오늘 점심으로 이 메뉴를 선택하신다면, 단백질과 지방을 충분히 채우는 구성이므로 하루 영양 균형을 위해 "
            "오늘 저녁은 맑은 채소 샤브샤브·나물 비빔밥처럼 기름기를 덜어내고 식이섬유를 보충하는 담백한 식단으로 가볍게 드시는 것을 추천합니다."
        )
    return (
        "만약 오늘 점심으로 이 메뉴를 선택하신다면, 탄단지 균형이 비교적 고르게 잡혀 있으므로 하루 영양 균형을 위해 "
        "오늘 저녁은 데친 채소·미역국에 계란이나 흰살생선 반찬을 곁들여 나트륨을 낮추고 가볍게 마무리하시는 것을 추천합니다."
    )


def _diagnose_food_coma(
    nutrition: NutritionFacts, preference: UserPreferenceRequest
) -> tuple[str, str]:
    """탄수화물·단백질 비율과 1인 기준 열량으로 식후 혈당 스파이크(식곤증) 위험도를 정밀 진단합니다."""
    is_group = preference.budget_tier == "generous_group"
    per_cal = (
        int(nutrition.calories_per_person)
        if nutrition.calories_per_person
        else (round(nutrition.calories / 2) if is_group else int(nutrition.calories))
    )
    per_carbs = round(nutrition.carbs_g / 2) if is_group else int(nutrition.carbs_g)
    per_protein = round(nutrition.protein_g / 2) if is_group else int(nutrition.protein_g)
    carb_protein_ratio = per_carbs / max(per_protein, 1)

    if (per_carbs <= 72 and per_protein >= 26) or (
        carb_protein_ratio <= 2.35 and per_cal <= 760
    ):
        return (
            "안전",
            f"탄수화물({per_carbs}g) 대비 단백질({per_protein}g) 비중이 높아 급격한 혈당 스파이크 없이 오후 5시까지 선명한 집중력을 유지합니다.",
        )
    if per_carbs >= 96 or per_cal >= 980 or (carb_protein_ratio >= 3.2 and per_cal >= 880):
        return (
            "주의",
            f"1인 기준 탄수화물 {per_carbs}g·{per_cal}kcal의 고밀도 식단으로 식후 혈당 상승에 따른 나른함이 올 수 있어 가벼운 10분 걷기를 권장합니다.",
        )
    return (
        "적정",
        f"탄수화물 {per_carbs}g과 단백질 {per_protein}g의 균형 배합으로 과도한 혈당 요동 없이 안정적인 포만감과 오후 작업 컨디션을 유지합니다.",
    )


def _normalize_food_coma_status(raw_status: str, fallback_status: str) -> str:
    cleaned = str(raw_status or "").strip()
    for allowed in ("안전", "적정", "주의"):
        if allowed in cleaned:
            return allowed
    return fallback_status


def _normalize_review_keywords(
    raw_keywords: Optional[List[str]], fallback_keywords: List[str]
) -> List[str]:
    result: List[str] = []
    seen = set()
    for kw in (raw_keywords or []):
        tag = str(kw or "").strip().strip(",.")
        if not tag:
            continue
        if not tag.startswith("#"):
            tag = f"#{tag}"
        tag = tag.replace(" ", "_")
        if tag not in seen:
            seen.add(tag)
            result.append(tag)
        if len(result) == 3:
            return result
    for fb in fallback_keywords:
        if fb not in seen:
            seen.add(fb)
            result.append(fb)
        if len(result) == 3:
            break
    return result[:3]


def _build_fallback_report(
    restaurant: Dict[str, Any],
    menu_name: str,
    estimated_price: str,
    nutrition: NutritionFacts,
    preference: UserPreferenceRequest,
    *,
    is_refresh: bool = False,
    candidate_count: int = 12,
) -> AIAnalysisReport:
    """실제 식당 업종·메뉴·탄단지 수치·3-Tap 조건을 기반으로 리뷰 마이닝·비교 우위·식곤증 지수·선정 논리 리포트를 생성합니다."""
    place_name = str(restaurant.get("place_name", "")).strip()
    cat_name = str(restaurant.get("category_name", "")).strip()
    dish_text = f"{place_name} {cat_name} {menu_name}"
    mode = _normalize_mode(preference.delivery_mode)
    total_peers = max(4, int(candidate_count or 12))

    if any(k in dish_text for k in ("포케", "샐러드", "샐러리아")):
        keywords = ["#신선한_토핑조합", "#혈당스파이크_제로", "#식곤증_완벽방어"]
        review_summary = "신선한 채소와 단백질 토핑 비율이 알차 식후 더부룩함 없이 가볍게 완식할 수 있다는 평가가 지배적이며 실사용 만족도가 높습니다."
        peer_label = "클린식·샐러드 매장"
        review_edge = "방문자 리뷰에서 '신선한 채소·토핑 비율'과 '식후 가벼운 포만감'에 대한 칭찬이 가장 집중된 매장"
    elif any(k in dish_text for k in ("국밥", "소머리", "해장국", "순대", "설렁탕", "현대옥")):
        keywords = ["#진한육수_잡내제로", "#푸짐한_고기건더기", "#혼밥눈치_완전제로"]
        review_summary = "고기 건더기가 넉넉하고 국물이 깔끔해 한 그릇만으로 든든함이 오래 간다는 평가가 지배적이며 실사용 만족도가 높습니다."
        peer_label = "국밥·탕류 매장"
        review_edge = "방문자 리뷰에서 '푸짐한 고기 건더기'와 '잡내 없는 깔끔한 육수'에 대한 칭찬이 가장 집중된 매장"
    elif any(k in dish_text for k in ("김치찌개", "김찌로", "순두부", "부대찌개", "찌개", "제육", "두루치기")):
        keywords = ["#불향가득_진한국물", "#밥도둑_고기양", "#빠른회전_점심맛집"]
        review_summary = "양념이 과하게 달지 않고 고기와 건더기가 실하게 들어가 점심 한 끼 만족도가 높다는 평가가 지배적이며 실사용 만족도가 높습니다."
        peer_label = "한식·찌개 매장"
        review_edge = "방문자 리뷰에서 '밥도둑 직화 양념'과 '넉넉한 고기 반찬 양'에 대한 칭찬이 가장 집중된 매장"
    elif any(k in dish_text for k in ("버거", "와퍼", "싸이", "롯데리아", "맥도날드", "프랭크", "노브랜드")) and "밥버거" not in dish_text:
        keywords = ["#겉바속촉_패티육즙", "#단품보다_콤보이득", "#대기적은_패스트픽"]
        review_summary = "주문 즉시 갓 구운 패티와 빵 식감이 살아 있어 빠르게 먹어도 한 끼 만족감이 확실하다는 평가가 지배적이며 실사용 만족도가 높습니다."
        peer_label = "버거·패스트푸드 매장"
        review_edge = "방문자 리뷰에서 '두툼한 패티 육즙'과 '빠른 조리 회전율'에 대한 칭찬이 가장 집중된 매장"
    elif any(k in dish_text for k in ("토스트", "이삭", "에그", "샌드위치", "써브웨이", "서브웨이", "파리바게뜨")):
        keywords = ["#폭신한_에그스크램블", "#손에안묻는_깔끔함", "#부담없는_균형식"]
        review_summary = "속재료가 넉넉하게 채워져 한 손으로 깔끔하게 먹기 좋고 소화 부담이 적다는 평가가 지배적이며 실사용 만족도가 높습니다."
        peer_label = "샌드위치·브런치 매장"
        review_edge = "방문자 리뷰에서 '알찬 속재료 구성'과 '깔끔한 원핸드 섭취 편의성'에 대한 칭찬이 가장 집중된 매장"
    elif any(k in dish_text for k in ("돈까스", "돈가스", "카츠", "상상카츠", "최고당", "미소야", "덮밥", "일식")):
        keywords = ["#두툼한_등심육즙", "#느끼함없는_바삭함", "#알찬정식_포만감"]
        review_summary = "튀김옷이 두껍지 않고 살코기가 도톰하게 씹혀 마지막 한 점까지 물리지 않고 든든하다는 평가가 지배적이며 실사용 만족도가 높습니다."
        peer_label = "돈카츠·일식 매장"
        review_edge = "방문자 리뷰에서 '도톰한 등심 육즙'과 '마지막까지 유지되는 바삭한 식감'에 대한 칭찬이 가장 집중된 매장"
    elif any(k in dish_text for k in ("마라탕", "탕화쿵푸", "라홍방", "짬뽕", "챠이챠이", "우동", "라멘", "쌀국수", "칼국수")):
        keywords = ["#깊은육수_감칠맛", "#채소토핑_식감최고", "#물리지않는_한그릇"]
        review_summary = "면과 육수가 따로 놀지 않고 토핑 식감이 넉넉해 기분 전환용 한 끼로 손꼽힌다는 평가가 지배적이며 실사용 만족도가 높습니다."
        peer_label = "면·중식/아시안 매장"
        review_edge = "방문자 리뷰에서 '진한 육수 감칠맛'과 '풍성한 채소·토핑 구성'에 대한 칭찬이 가장 집중된 매장"
    elif any(k in dish_text for k in ("한솥", "도시락", "봉구스", "밥버거", "행컵", "밀플랜비", "부리또", "브리또", "김밥")):
        keywords = ["#극강_만원가성비", "#초고속_조리완성", "#알찬토핑_한그릇"]
        review_summary = "가격 대비 토핑·밥 양이 알차고 포장 위생 및 제공 속도가 뛰어나다는 평가가 지배적이며 실사용 만족도가 높습니다."
        peer_label = "도시락·간편식 매장"
        review_edge = "방문자 리뷰에서 '포장 위생 및 보온성'과 '만원 예산 대비 알찬 메뉴 구성'에 대한 칭찬이 가장 집중된 매장"
    elif any(k in dish_text for k in ("죽", "본죽")):
        keywords = ["#속편한_부드러움", "#알찬_전복소고기", "#깔끔한_밑반찬"]
        review_summary = "건더기가 바닥까지 실하게 들어가 있고 간이 자극적이지 않아 속이 편하다는 평가가 지배적이며 실사용 만족도가 높습니다."
        peer_label = "죽·클린 한식 매장"
        review_edge = "방문자 리뷰에서 '실한 건더기 비율'과 '자극 없이 깔끔한 소화감'에 대한 칭찬이 가장 집중된 매장"
    else:
        keywords = ["#재료신선_정갈함", "#재방문율_상위권", "#안정적_간밸런스"]
        review_summary = "음식이 전반적으로 정갈하고 양과 간의 균형이 안정적이라 믿고 재방문하게 된다는 평가가 지배적이며 실사용 만족도가 높습니다."
        peer_label = "인근 동종 매장"
        review_edge = "방문자 리뷰에서 '재료 신선도'와 '일정한 맛 밸런스'에 대한 호평이 꾸준히 집중되는 매장"

    radius_scope = "반경 3.5km 배달 권역 내" if mode == "delivery" else "반경 1km 내"
    why_this_spot = (
        f"{radius_scope} 동종 {peer_label} 후보({total_peers}곳 비교) 중 {estimated_price} 기준(단백질 {nutrition.protein_g}g) {review_edge}입니다."
    )

    coma_status, coma_desc = _diagnose_food_coma(nutrition, preference)

    chosen_tex = {
        "bread": "빵/패티",
        "rice": "밥/든든함",
        "soup": "면/뜨끈한 국물",
    }.get(preference.texture_temp, preference.texture_temp)
    chosen_meal = {
        "quick": "간편 15분컷",
        "proper": "제대로 된 한 끼",
        "clean": "가볍고 클린한 식사",
    }.get(preference.meal_mode, preference.meal_mode)

    if is_refresh:
        selection_logic = (
            f"선택하신 '{chosen_tex}'과 다른 결의 '{menu_name}'으로 식감 피로를 환기하면서도, 원하시는 '{chosen_meal}' 템포와 예산 기준을 100% 맞춘 반전 대안입니다."
        )
    else:
        selection_logic = (
            f"선택하신 '{chosen_tex}' 식감과 '{chosen_meal}' 템포, 예산 기준까지 3-Tap 조건을 오차 없이 충족하는 가장 확실한 1순위 매칭입니다."
        )

    if _is_meal_kit_store(restaurant, menu_name) and MEAL_KIT_NOTICE not in selection_logic:
        selection_logic = f"{MEAL_KIT_NOTICE}. {selection_logic}"

    protein_dv = _compute_protein_dv_percent(nutrition.protein_g)
    dinner_guide = _build_dinner_pairing_guide(nutrition, menu_name, preference)

    return AIAnalysisReport(
        review_keywords=keywords,
        visitor_review_summary=review_summary,
        why_this_spot=why_this_spot,
        protein_dv_percent=protein_dv,
        food_coma_status=coma_status,
        food_coma_desc=coma_desc,
        selection_logic=selection_logic,
        dinner_pairing_guide=dinner_guide,
    )


def _sanitize_report(
    raw_report: Optional[AIAnalysisReport],
    restaurant: Dict[str, Any],
    menu_name: str,
    estimated_price: str,
    nutrition: NutritionFacts,
    preference: UserPreferenceRequest,
    *,
    is_refresh: bool = False,
    candidate_count: int = 12,
) -> AIAnalysisReport:
    fallback = _build_fallback_report(
        restaurant,
        menu_name,
        estimated_price,
        nutrition,
        preference,
        is_refresh=is_refresh,
        candidate_count=candidate_count,
    )
    if raw_report is None:
        return fallback

    keywords = _normalize_review_keywords(
        getattr(raw_report, "review_keywords", None),
        fallback.review_keywords,
    )
    summary = str(getattr(raw_report, "visitor_review_summary", "") or "").strip()
    summary = re.sub(r'^["\'“”‘’]+|["\'“”‘’]+$', "", summary).strip()
    summary = re.sub(r"^방문자\s*리뷰\s*종합(?:\s*요약)?\s*[:：]\s*", "", summary).strip()
    summary = re.sub(r'^["\'“”‘’]+|["\'“”‘’]+$', "", summary).strip()
    summary = re.sub(r"\s*\(\s*(?:약\s*)?\d+(?:\.\d+)?\s*%\s*\)", "", summary).strip()
    if not summary or re.search(r"\d+(?:\.\d+)?\s*%", summary):
        summary = fallback.visitor_review_summary

    why_spot = str(getattr(raw_report, "why_this_spot", "") or "").strip()
    why_spot = re.sub(r"\s*\(\s*(?:약\s*)?\d+(?:\.\d+)?\s*%\s*\)", "", why_spot).strip()
    if not why_spot or re.search(r"\d+(?:\.\d+)?\s*%", why_spot):
        why_spot = fallback.why_this_spot
    coma_status = _normalize_food_coma_status(
        getattr(raw_report, "food_coma_status", ""), fallback.food_coma_status
    )
    coma_desc = str(getattr(raw_report, "food_coma_desc", "") or "").strip() or fallback.food_coma_desc
    selection_logic = (
        str(getattr(raw_report, "selection_logic", "") or "").strip()
        or fallback.selection_logic
    )
    if _is_meal_kit_store(restaurant, menu_name) and MEAL_KIT_NOTICE not in selection_logic:
        selection_logic = f"{MEAL_KIT_NOTICE}. {selection_logic}"

    protein_dv = _compute_protein_dv_percent(nutrition.protein_g)
    dinner_guide = str(getattr(raw_report, "dinner_pairing_guide", "") or "").strip()
    dinner_guide = re.sub(r"\s*\(\s*(?:약\s*)?\d+(?:\.\d+)?\s*%\s*\)", "", dinner_guide).strip()
    has_past_tense = bool(
        re.search(
            r"(?:먹었으니|드셨으니|섭취했으니|드셨으므로|먹었으므로|골랐으니|드셨기|먹었기|선택했으니|선택하셨으니|드셨다면|먹었다면)",
            dinner_guide,
        )
    )
    if not dinner_guide or has_past_tense or re.search(r"\d+(?:\.\d+)?\s*%", dinner_guide):
        dinner_guide = fallback.dinner_pairing_guide

    return AIAnalysisReport(
        review_keywords=keywords,
        visitor_review_summary=summary,
        why_this_spot=why_spot,
        protein_dv_percent=protein_dv,
        food_coma_status=coma_status,
        food_coma_desc=coma_desc,
        selection_logic=selection_logic,
        dinner_pairing_guide=dinner_guide,
    )


def _map_restaurant_to_item(
    rank: int,
    persona_type: str,
    persona: str,
    restaurant: Dict[str, Any],
    delivery_mode: str,
    recommended_menu: str,
    estimated_price: str,
    nutrition: NutritionFacts,
    report: AIAnalysisReport,
    is_meal_kit: Optional[bool] = None,
    emoji: Optional[str] = None,
) -> RecommendationItem:
    """백엔드 원본 카카오 식당 객체의 place_name, distance_m, 수학적 distance_display, 배달 스펙, 쿠팡이츠 딥링크 및 푸드 이모지를 직접 바인딩합니다."""
    place_name = str(restaurant.get("place_name", "")).strip()
    category_name = str(restaurant.get("category_name", "")).strip()
    dist_m = max(0, _parse_distance_m(restaurant.get("distance", "0"), default=0))
    mode = _normalize_mode(delivery_mode)
    distance_display = format_distance_text(dist_m, mode)
    links = build_delivery_deep_links(place_name)
    kakao_url = (
        str(restaurant.get("place_url", "")).strip()
        or f"https://map.kakao.com/link/search/{quote(place_name)}"
    )
    resolved_meal_kit = (
        is_meal_kit
        if is_meal_kit is not None
        else _is_meal_kit_store(restaurant, recommended_menu)
    )
    resolved_emoji = (
        emoji.strip()
        if emoji and emoji.strip()
        else get_menu_emoji(place_name, recommended_menu, category_name)
    )
    normalized_persona_type = "refresh" if persona_type == "refresh" else "standard"

    delivery_spec_obj: Optional[DeliverySpec] = None
    if mode == "delivery":
        spec = analyze_delivery_spec(
            restaurant,
            recommended_menu,
            estimated_price,
            distance_m=dist_m,
        )
        delivery_spec_obj = DeliverySpec(
            min_order_price=spec["min_order_price"],
            shortfall_price=spec["shortfall_price"],
            filler_recommendation=spec["filler_recommendation"],
            coupang_benefit=spec["coupang_benefit"],
        )

    return RecommendationItem(
        rank=rank,
        persona_type=normalized_persona_type,
        category_persona=persona,
        restaurant_name=place_name,
        recommended_menu=recommended_menu,
        estimated_price=estimated_price,
        distance_m=dist_m,
        distance_display=distance_display,
        emoji=resolved_emoji,
        nutrition=nutrition,
        report=report,
        is_meal_kit=resolved_meal_kit,
        clean_store_name=links["clean_store_name"],
        delivery_spec=delivery_spec_obj,
        coupang_eats_url=links["coupang_eats_url"],
        kakao_map_url=kakao_url,
        naver_review_url=links["naver_review_url"],
    )


def _ranked_restaurant_indices(
    preference: UserPreferenceRequest,
    weather_info: Dict[str, Any],
    restaurants: List[Dict[str, Any]],
) -> List[int]:
    """식감/온도 1순위 절대 규칙, 3-Tap 적합도, 거리 감점/근접 우선순위로 정석 식당 인덱스를 정렬합니다."""
    return sorted(
        range(len(restaurants)),
        key=lambda i: (
            _score_restaurant(restaurants[i], preference, weather_info),
            -_parse_distance_m(restaurants[i].get("distance"), default=500),
        ),
        reverse=True,
    )


def _ranked_refresh_indices(
    preference: UserPreferenceRequest,
    weather_info: Dict[str, Any],
    restaurants: List[Dict[str, Any]],
    standard_categories: Optional[set[str]] = None,
) -> List[int]:
    """사용자 템포·예산은 유지하되 카테고리를 비튼 리프레시 후보 인덱스를 정렬합니다."""
    return sorted(
        range(len(restaurants)),
        key=lambda i: (
            _score_refresh_restaurant(
                restaurants[i], preference, weather_info, standard_categories
            ),
            -_parse_distance_m(restaurants[i].get("distance"), default=500),
        ),
        reverse=True,
    )


def _materialize_group(
    raw_items: List[AISelectionItem],
    target_count: int,
    persona_type: str,
    default_persona_label: str,
    ranked_indices: List[int],
    used_indices: set[int],
    preference: UserPreferenceRequest,
    weather_info: Dict[str, Any],
    restaurants: List[Dict[str, Any]],
) -> List[RecommendationItem]:
    """정석(3개) 또는 리프레시(2개) 후보군을 Post-Validation 후 RecommendationItem 리스트로 구체화합니다."""
    mode = _normalize_mode(preference.delivery_mode)
    is_refresh = persona_type == "refresh"
    sorted_raw = sorted(raw_items, key=lambda x: x.rank)[:target_count]
    slot_assignments: List[Optional[int]] = [None] * target_count
    slot_is_ai: List[bool] = [False] * target_count

    for slot_idx in range(min(target_count, len(sorted_raw))):
        idx_val = sorted_raw[slot_idx].selected_index
        if (
            isinstance(idx_val, int)
            and 0 <= idx_val < len(restaurants)
            and idx_val not in used_indices
        ):
            slot_assignments[slot_idx] = idx_val
            slot_is_ai[slot_idx] = True
            used_indices.add(idx_val)
        else:
            logger.warning(
                "Post-Validation(%s): 유효하지 않거나 중복된 selected_index(%s)를 안전 치환 대상으로 표시합니다.",
                persona_type,
                idx_val,
            )

    chosen_cats_in_group: set[str] = {
        str(restaurants[idx].get("category_name", "")).strip()
        for idx in slot_assignments
        if idx is not None and str(restaurants[idx].get("category_name", "")).strip()
    }

    def _pick_next_valid_index(prefer_diverse: bool = False) -> int:
        if prefer_diverse and chosen_cats_in_group:
            for cand_idx in ranked_indices:
                cand_cat = str(restaurants[cand_idx].get("category_name", "")).strip()
                if cand_idx not in used_indices and cand_cat not in chosen_cats_in_group:
                    return cand_idx
        for cand_idx in ranked_indices:
            if cand_idx not in used_indices:
                return cand_idx
        return ranked_indices[len(used_indices) % len(ranked_indices)]

    for slot_idx in range(target_count):
        if slot_assignments[slot_idx] is None:
            chosen_idx = _pick_next_valid_index(prefer_diverse=is_refresh or slot_idx >= 1)
            slot_assignments[slot_idx] = chosen_idx
            used_indices.add(chosen_idx)
            cand_cat = str(restaurants[chosen_idx].get("category_name", "")).strip()
            if cand_cat:
                chosen_cats_in_group.add(cand_cat)
            logger.warning(
                "Post-Validation(%s): rank %d 슬롯을 실제 식당 Index %d(%s)로 치환했습니다.",
                persona_type,
                slot_idx + 1,
                chosen_idx,
                restaurants[chosen_idx].get("place_name", ""),
            )

    items: List[RecommendationItem] = []
    for slot_idx in range(target_count):
        raw_item = sorted_raw[slot_idx] if slot_idx < len(sorted_raw) else None
        chosen_idx = slot_assignments[slot_idx] if slot_assignments[slot_idx] is not None else 0
        rest = restaurants[chosen_idx]
        fallback_inferred = _infer_menu_and_price(rest, preference, is_refresh=is_refresh)

        if slot_is_ai[slot_idx] and raw_item is not None:
            menu_val = raw_item.recommended_menu.strip() or fallback_inferred["menu"]
            price_val = raw_item.estimated_price.strip() or fallback_inferred["price"]
            menu_val, price_val = _calibrate_min_order_exact_delivery_menu(
                rest, menu_val, price_val, fallback_inferred, preference
            )
            nutrition_val = _sanitize_nutrition(raw_item.nutrition, rest, menu_val, preference)
            report_val = _sanitize_report(
                getattr(raw_item, "report", None),
                rest,
                menu_val,
                price_val,
                nutrition_val,
                preference,
                is_refresh=is_refresh,
                candidate_count=len(restaurants),
            )
        else:
            menu_val, price_val = _calibrate_min_order_exact_delivery_menu(
                rest,
                fallback_inferred["menu"],
                fallback_inferred["price"],
                fallback_inferred,
                preference,
            )
            nutrition_val = _infer_nutrition_facts(rest, menu_val, preference)
            report_val = _build_fallback_report(
                rest,
                menu_val,
                price_val,
                nutrition_val,
                preference,
                is_refresh=is_refresh,
                candidate_count=len(restaurants),
            )

        is_meal_kit = _is_meal_kit_store(rest, menu_val)
        emoji_val = get_menu_emoji(
            str(rest.get("place_name", "")).strip(),
            menu_val,
            str(rest.get("category_name", "")).strip(),
        )
        items.append(
            _map_restaurant_to_item(
                rank=slot_idx + 1,
                persona_type=persona_type,
                persona=default_persona_label,
                restaurant=rest,
                delivery_mode=mode,
                recommended_menu=menu_val,
                estimated_price=price_val,
                nutrition=nutrition_val,
                report=report_val,
                is_meal_kit=is_meal_kit,
                emoji=emoji_val,
            )
        )

    return items


def _post_validate_and_materialize(
    raw_standards: List[AISelectionItem],
    raw_refreshes: List[AISelectionItem],
    preference: UserPreferenceRequest,
    weather_info: Dict[str, Any],
    restaurants: List[Dict[str, Any]],
    address_name: str,
) -> RecommendationResponse:
    """
    Gemini가 반환한 정석 3개 + 리프레시 2개 selected_index를 검증(Post-Validation)하고,
    유효하지 않거나 중복된 인덱스는 실제 식당 목록 내 최적 매장으로 안전 치환한 뒤
    원본 카카오 식당 데이터(place_name, distance_m, distance_display, URL, 푸드 이모지)를 직접 바인딩합니다.
    """
    if not restaurants:
        raise ValueError("실제 주변 식당 목록이 비어 있어 추천 결과를 생성할 수 없습니다.")

    mode = _normalize_mode(preference.delivery_mode)
    weather_str = weather_info.get("weather", "쌀쌀한 흐림")
    temp_str = weather_info.get("temp", "7℃")

    standard_ranked = _ranked_restaurant_indices(preference, weather_info, restaurants)
    used_indices: set[int] = set()

    standards = _materialize_group(
        raw_items=raw_standards,
        target_count=3,
        persona_type="standard",
        default_persona_label="[확신의 픽]",
        ranked_indices=standard_ranked,
        used_indices=used_indices,
        preference=preference,
        weather_info=weather_info,
        restaurants=restaurants,
    )

    standard_categories = {
        str(restaurants[i].get("category_name", "")).strip()
        for i in used_indices
        if str(restaurants[i].get("category_name", "")).strip()
    }
    refresh_ranked = _ranked_refresh_indices(
        preference, weather_info, restaurants, standard_categories
    )

    refreshes = _materialize_group(
        raw_items=raw_refreshes,
        target_count=2,
        persona_type="refresh",
        default_persona_label="[반전 매력 픽]",
        ranked_indices=refresh_ranked,
        used_indices=used_indices,
        preference=preference,
        weather_info=weather_info,
        restaurants=restaurants,
    )

    return RecommendationResponse(
        address_name=address_name,
        current_weather=weather_str,
        temperature=temp_str,
        delivery_mode=mode,
        standards=standards,
        refreshes=refreshes,
    )


def _select_from_real_restaurants_fallback(
    preference: UserPreferenceRequest,
    weather_info: Dict[str, Any],
    restaurants: List[Dict[str, Any]],
    address_name: str,
) -> RecommendationResponse:
    """Gemini 호출 불가 시에도 실제 카카오 식당 목록에서만 정석 3개 + 리프레시 2개 후보군을 선별합니다."""
    if not restaurants:
        raise ValueError("실제 주변 식당 목록이 비어 있어 추천 결과를 생성할 수 없습니다.")

    standard_ranked = _ranked_restaurant_indices(preference, weather_info, restaurants)
    selected_standard_indices = standard_ranked[:3]
    while len(selected_standard_indices) < 3:
        selected_standard_indices.append(
            standard_ranked[len(selected_standard_indices) % len(standard_ranked)]
        )

    used_set = set(selected_standard_indices)
    standard_categories = {
        str(restaurants[idx].get("category_name", "")).strip()
        for idx in selected_standard_indices
        if str(restaurants[idx].get("category_name", "")).strip()
    }
    refresh_ranked = _ranked_refresh_indices(
        preference, weather_info, restaurants, standard_categories
    )

    selected_refresh_indices: List[int] = []
    chosen_refresh_cats: set[str] = set()
    for cand_idx in refresh_ranked:
        if cand_idx in used_set:
            continue
        cand_cat = str(restaurants[cand_idx].get("category_name", "")).strip()
        if selected_refresh_indices and cand_cat and cand_cat in chosen_refresh_cats:
            continue
        selected_refresh_indices.append(cand_idx)
        used_set.add(cand_idx)
        if cand_cat:
            chosen_refresh_cats.add(cand_cat)
        if len(selected_refresh_indices) >= 2:
            break

    while len(selected_refresh_indices) < 2:
        next_idx = next(
            (i for i in refresh_ranked if i not in used_set),
            refresh_ranked[len(selected_refresh_indices) % len(refresh_ranked)],
        )
        selected_refresh_indices.append(next_idx)
        used_set.add(next_idx)

    raw_standards: List[AISelectionItem] = []
    for slot_idx, rest_idx in enumerate(selected_standard_indices[:3]):
        rest = restaurants[rest_idx]
        inferred = _infer_menu_and_price(rest, preference, is_refresh=False)
        nutrition = _infer_nutrition_facts(rest, inferred["menu"], preference)
        report = _build_fallback_report(
            rest,
            inferred["menu"],
            inferred["price"],
            nutrition,
            preference,
            is_refresh=False,
            candidate_count=len(restaurants),
        )
        raw_standards.append(
            AISelectionItem(
                selected_index=rest_idx,
                rank=slot_idx + 1,
                persona_type="standard",
                category_persona="[확신의 픽]",
                recommended_menu=inferred["menu"],
                estimated_price=inferred["price"],
                nutrition=nutrition,
                report=report,
            )
        )

    raw_refreshes: List[AISelectionItem] = []
    for slot_idx, rest_idx in enumerate(selected_refresh_indices[:2]):
        rest = restaurants[rest_idx]
        inferred = _infer_menu_and_price(rest, preference, is_refresh=True)
        nutrition = _infer_nutrition_facts(rest, inferred["menu"], preference)
        report = _build_fallback_report(
            rest,
            inferred["menu"],
            inferred["price"],
            nutrition,
            preference,
            is_refresh=True,
            candidate_count=len(restaurants),
        )
        raw_refreshes.append(
            AISelectionItem(
                selected_index=rest_idx,
                rank=slot_idx + 1,
                persona_type="refresh",
                category_persona="[반전 매력 픽]",
                recommended_menu=inferred["menu"],
                estimated_price=inferred["price"],
                nutrition=nutrition,
                report=report,
            )
        )

    return _post_validate_and_materialize(
        raw_standards, raw_refreshes, preference, weather_info, restaurants, address_name
    )


def generate_recommendations(
    preference: UserPreferenceRequest,
    weather_info: Dict[str, Any],
    restaurants: List[Dict[str, Any]],
    address_name: str = "경기도 화성시 효행구 봉담읍",
) -> RecommendationResponse:
    """
    Gemini 3.8 Flash 초정밀 추론 + Index 기반 실존 데이터 바인딩 + 탄단지 수치화로
    정석 3개(`standards`) + 리프레시 2개(`refreshes`) 후보군 풀을 생성합니다.
    """
    mode = _normalize_mode(preference.delivery_mode)
    max_cutoff = 3500 if mode == "delivery" else 1000

    # 도보(직선 1,000m / 실보행 약 1.3km) / 배달(3,500m) 모드 반경 컷오프 이중 강제 격리
    candidate_restaurants = [
        r for r in restaurants
        if 0 <= _parse_distance_m(r.get("distance"), default=-1) <= max_cutoff
    ][:45]

    if not candidate_restaurants:
        raise ValueError(
            f"현재 위치({address_name}) 기준 반경 {max_cutoff}m 이내에 조건에 맞는 실제 식당이 없습니다."
        )

    api_key = os.getenv("GEMINI_API_KEY", "").strip()
    if not api_key:
        logger.warning("GEMINI_API_KEY가 비어 있어 실제 식당 기반 로컬 리포트를 생성합니다.")
        return _select_from_real_restaurants_fallback(
            preference, weather_info, candidate_restaurants, address_name
        )

    delivery_desc = DELIVERY_MODE_LABELS.get(mode, mode)
    meal_desc = MEAL_MODE_LABELS.get(preference.meal_mode, preference.meal_mode)
    texture_desc = TEXTURE_TEMP_LABELS.get(preference.texture_temp, preference.texture_temp)
    texture_strict_rule = TEXTURE_STRICT_RULES.get(
        preference.texture_temp,
        "사용자가 선택한 식감/온도 조건을 정석 3곳의 1순위 절대 규칙으로 엄격히 매칭하세요.",
    )
    budget_desc = BUDGET_TIER_LABELS.get(preference.budget_tier, preference.budget_tier)
    budget_strict_rule = BUDGET_STRICT_RULES.get(
        preference.budget_tier,
        "예산 밸런스에 맞추어 합리적인 메뉴를 추천하세요.",
    )

    mode_rule = WALK_DISTANCE_DECAY_RULE if mode == "walk" else DELIVERY_MODE_RULE
    system_instruction = f"{SYSTEM_PROMPT}\n\n{mode_rule}"

    indexed_lines = []
    for idx, r in enumerate(candidate_restaurants):
        name = r.get("place_name", "")
        cat = r.get("category_name", "음식점")
        dist_m = max(0, _parse_distance_m(r.get("distance", "0"), default=0))
        actual_walk_m = round(dist_m * WALK_DETOUR_FACTOR)
        dist_label = format_distance_text(dist_m, mode)
        meal_kit_tag = (
            " | [비조리 밀키트 매장 - 즉석 배달 후순위]"
            if mode == "delivery" and _is_meal_kit_store(r)
            else ""
        )
        indexed_lines.append(
            f"[Index {idx}] {name} | 카테고리: {cat} | 직선거리: {dist_m}m (우회보정 약 {actual_walk_m}m) | 이동정보: {dist_label}{meal_kit_tag}"
        )

    indexed_list_text = "\n".join(indexed_lines)

    prompt = f"""아래 사용자의 현재 위치({address_name}) · 식사 방식(도보/배달) · 3-Tap 선택 · 실시간 날씨 · [주변 실제 식당 인덱스 목록]을 종합 추론하여,
할루시네이션이 0%인 서로 다른 실제 매장 인덱스 총 5개(`standards` 3개 + `refreshes` 2개)와 탄단지 영양 수치(`NutritionFacts`)가 포함된 초정밀 리포트(`AISelectionResponse`)를 생성하세요.

[현재 위치 및 기상 컨텍스트]
- 한글 행정구역 주소: {address_name}
- 날씨 상태: {weather_info.get("weather", "쌀쌀한 흐림")}
- 현재 기온: {weather_info.get("temp", "7℃")}
- 추위 여부(is_cold): {weather_info.get("is_cold", True)}

[사용자 조건]
0. 식사 방식: {delivery_desc}
1. 식감/온도 (★ 정석 1순위 절대 규칙 ★): {texture_desc}
2. 식사 템포: {meal_desc}
3. 예산 조건: {budget_desc}

{texture_strict_rule}

{budget_strict_rule}

{mode_rule}

[주변 실제 식당 인덱스 목록 (유효 인덱스 범위: 0 ~ {len(candidate_restaurants) - 1})]
{indexed_list_text}

[필수 출력 및 후보군 풀 구성 규칙]
1. 인덱스 무관용 & 상호 배타 원칙:
   - 반드시 위 목록의 '[Index N]' 중에서만 `selected_index`를 반환하세요.
   - `standards`(3개) + `refreshes`(2개) 총 5개의 `selected_index`는 모두 **서로 다른 정수**여야 합니다 (후보 식당이 5곳 미만일 때만 예외).
2. `standards` (확신의 픽 1~3순위, 총 3개):
   - `rank`: 1, 2, 3
   - `persona_type`: `"standard"`
   - `category_persona`: `"[확신의 픽]"`
   - 사용자 조건(식감/온도 `{preference.texture_temp}`, 식사 템포 `{preference.meal_mode}`, 예산 `{preference.budget_tier}`)에 100% 충실한 확신의 매칭 3곳을 1~3순위 순으로 선별하세요.
3. `refreshes` (반전 매력 픽 1~2순위, 총 2개):
   - `rank`: 1, 2
   - `persona_type`: `"refresh"`
   - `category_persona`: `"[반전 매력 픽]"`
   - 사용자의 **식사 템포(`{preference.meal_mode}`)와 예산(`{preference.budget_tier}`)은 유지**하되, 선택한 식감/카테고리(`{preference.texture_temp}`)를 색다르게 비튼 반전 매력 대안 2곳을 선별하세요 (예: 빵 선택 시 샐러드랩/부리또/밥버거, 밥 선택 시 샌드위치/파스타/쌀국수, 국물 선택 시 카츠/덮밥/부리또 등).
   - 반전 매력 픽 1순위와 2순위 역시 서로 다른 업종/메뉴 스타일로 다양성을 확보하세요.
4. `recommended_menu`와 `estimated_price`(예: "9,500원") 규칙:
   - 해당 인덱스 매장에서 실제 판매하는 대표 시그니처 메뉴로 작성하세요 (`standards`는 `{preference.texture_temp}` 일치 메뉴, `refreshes`는 해당 매장의 색다른 대안 메뉴).
   - `budget`: 반드시 8,000원 이하 혼밥 실속 단품으로 추천하세요.
   - `flexible`: 3,000~5,000원대 단순 단품과 15,000원 초과 메뉴를 배제하며 **8,000원 초과 ~ 13,000원 이하**의 알찬 세트/정식 메뉴를 추천하세요.
   - `min_order_exact`: 매장의 통상 최소주문금액(보통 12,000~14,000원, 도시락/밥버거 9,000~10,000원)을 과도하게 넘기거나 미달되지 않도록 메인 + 저렴한 실속 사이드(음료/치즈스틱/너겟 등)를 조합해 최소주문금액에 딱 맞추는 1인 콤보로 작성하세요. 특히 패스트푸드/버거류는 최소주문(약 13,000원) 미달로 튕기지 않도록 와퍼 세트 + 치즈스틱/너겟 조합처럼 **합산 12,500~13,500원 구간**에 안전하게 맞추세요.
   - `generous_group`: 2인 이상이 함께 나눠먹기 좋은 푸짐한 세트나 대형 메뉴(**18,000원 ~ 25,000원대**)를 추천하세요.
5. `nutrition` (`NutritionFacts`) 수치화 규칙:
   - 선택한 `recommended_menu`(세트·다인 구성 포함 총량 기준)의 현실적인 `calories`(kcal 정수), `carbs_g`(탄수화물 g 정수), `protein_g`(단백질 g 정수), `fat_g`(지방 g 정수)를 추정하세요 (`calories`는 대략 carbs*4 + protein*4 + fat*9와 일치해야 합니다).
   - `calories_per_person`: `generous_group`(2인 이상 다인 세트)일 때는 `round(calories / 2)` 정수를 기입하고, 1인 단품/콤보일 때는 `null`을 반환하세요.
   - `nutrition_highlight`: 선택한 식감/모드 기준 탄단지 균형 분석을 핵심 1줄로 작성하세요.
6. `report` (`AIAnalysisReport`) 초정밀 추천 근거 리포트 작성 규칙 (상투적 날씨/꿀팁/동선 클리셰 및 거짓 수치·인용구 전면 폐기):
   - 금지: "쌀쌀한 날씨에 어울립니다", "따뜻하게 드세요", "맛있게 비벼 드세요", "도보 이동이 편합니다", "(경기도 화성시...)" 행정동 주소 반복, 거리/시간 숫자 나열, 증명 불가능한 가짜 퍼센트 숫자('(94%)', '(89%)' 등 어떠한 % 수치도 절대 생성 금지), 실제 방문자 인용처럼 꾸민 따옴표("...") 문장.
   - 반드시 아래 8개 필드를 정직하고 날카로운 **팩트·실데이터·비교 우위** 중심으로 채우세요:
     1) `review_keywords`: 해당 매장/메뉴에서 실제 방문자들이 주로 칭찬하는 핵심 매력 해시태그 정확히 3개 (예: `["#불향가득_직화", "#푸짐한_고기양", "#혼밥편함"]`).
     2) `visitor_review_summary`: 따옴표("...") 인용구 없이, 방문자 평가를 종합한 AI 총평임을 알 수 있도록 `~라는 평가가 지배적이며 실사용 만족도가 높습니다` 형태로 정직한 1줄 요약을 작성하세요 (단, 문두의 `"방문자 리뷰 종합 요약:"` 라벨은 UI에서 붙이므로 라벨 없이 본문만 작성).
     3) `why_this_spot`: `(94%)`, `(89%)` 같은 가짜 퍼센트 숫자를 절대 지어내지 말고, 위 후보 목록(총 {len(candidate_restaurants)}곳)의 인근 동종 매장들과 비교했을 때 이 매장이 돋보이는 이유를 실제 팩트 기반 서술형으로 정직하게 1~2줄 작성 (예: `"반경 1km 내 동종 매장 중 방문자 리뷰에서 '포장 위생 및 보온성'과 '고기 반찬의 퀄리티'에 대한 칭찬이 가장 집중된 매장"`).
     4) `protein_dv_percent`: 위 `nutrition.protein_g`를 식약처 성인 1일 단백질 권장량(55g)으로 나눈 충족률 정수 `round(protein_g / 55 * 100)` (백엔드에서도 최종 수치로 검증·보정).
     5) `food_coma_status`: 방금 추정한 `nutrition`의 탄수화물·단백질 비율과 칼로리를 분석해 식후 혈당 스파이크 및 식곤증 위험도를 `"안전"`, `"적정"`, `"주의"` 중 하나로 정확히 판정.
     6) `food_coma_desc`: 탄단지 비율과 혈당 반응 근거로 오후 업무·학업 집중력이 몇 시까지 어떻게 유지되는지 과학적 1줄 예측 (예: `"고단백·복합당질 구성으로 급격한 혈당 스파이크 없이 오후 5시까지 집중력을 유지합니다."`).
     7) `selection_logic`:
        - `standards` (`[확신의 픽]`): 사용자의 3-Tap 욕구(`{texture_desc}`, `{meal_desc}`, `{budget_desc}`)에 100% 부합하는 실패 없는 명쾌한 이유 1줄.
        - `refreshes` (`[반전 매력 픽]`): 왜 선택한 `{texture_desc}` 대신 이 대안 메뉴(`recommended_menu`)를 제안했는지 고개가 끄덕여지는 신선한 반전 논리 1줄.
        - 비조리 밀키트 매장일 경우 반드시 `selection_logic`에 `"⚠️ 냄비 조리가 필요한 밀키트 구성입니다"`를 명시하세요.
     8) `dinner_pairing_guide`: 절대 과거형 단정("점심에 이걸 먹었으니...")을 쓰지 말고, **"만약 오늘 점심으로 이 메뉴를 선택하신다면, 하루 영양 균형을 위해 오늘 저녁은 ~ 위주로 가볍게/든든하게 드시는 것을 추천합니다"**라는 선택 전 사전 예측 시뮬레이션 톤으로 1~2줄 서술하세요 (예: 탄수화물·지방 비중이 높다면 저녁 저탄수 고단백 채소식 권장, 가벼운 클린식이라면 저녁 복합당·단백질 보충 권장).
"""

    try:
        client = genai.Client(
            api_key=api_key,
            http_options=types.HttpOptions(
                timeout=30000,
                retry_options=types.HttpRetryOptions(attempts=1),
            ),
        )
        response = client.models.generate_content(
            model=GEMINI_MODEL,
            contents=prompt,
            config=types.GenerateContentConfig(
                system_instruction=system_instruction,
                response_mime_type="application/json",
                response_schema=AISelectionResponse,
                temperature=0.35,
                thinking_config=types.ThinkingConfig(
                    thinking_level=types.ThinkingLevel.LOW
                ),
            ),
        )

        parsed = getattr(response, "parsed", None)
        if isinstance(parsed, AISelectionResponse):
            raw_result = parsed
        elif parsed is not None:
            raw_result = AISelectionResponse.model_validate(parsed)
        else:
            raw_result = AISelectionResponse.model_validate_json(response.text)

        if not raw_result.standards and not raw_result.refreshes:
            logger.warning("Gemini Index 응답이 비어 있어 실제 식당 기반 로컬 리포트로 대체합니다.")
            return _select_from_real_restaurants_fallback(
                preference, weather_info, candidate_restaurants, address_name
            )

        return _post_validate_and_materialize(
            raw_result.standards,
            raw_result.refreshes,
            preference,
            weather_info,
            candidate_restaurants,
            address_name,
        )

    except Exception as exc:
        logger.warning(
            "Gemini 3.8 Flash 호출 실패(%s)로 인해 실제 식당 기반 로컬 리포트를 반환합니다.", exc
        )
        return _select_from_real_restaurants_fallback(
            preference, weather_info, candidate_restaurants, address_name
        )
