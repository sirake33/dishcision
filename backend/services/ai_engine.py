import json
import logging
import os
from pathlib import Path
from typing import Any, Dict, List
from urllib.parse import quote

from dotenv import load_dotenv
from google import genai
from google.genai import types

from backend.schemas import (
    RecommendationItem,
    RecommendationResponse,
    UserPreferenceRequest,
)

load_dotenv(Path(__file__).resolve().parents[2] / ".env")

logger = logging.getLogger(__name__)

GEMINI_MODEL = "gemini-3.8-flash"

MEAL_MODE_LABELS = {
    "quick": "간편 15분컷 (햄버거/토스트/밥버거/분식 등 빠르고 간편한 식사)",
    "proper": "제대로 된 한 끼 (든든한 밥/국밥/정식/메인 요리)",
    "clean": "가볍고 클린하게 (샐러드/포케/랩 등 부담 없는 건강식)",
}

TEXTURE_TEMP_LABELS = {
    "bread": "빵/패티 (버거, 토스트, 샌드위치, 랩 등)",
    "rice": "밥/든든함 (밥버거, 덮밥, 도시락, 한식 밥류)",
    "soup": "면/뜨끈한 국물 (국밥, 육개장, 짬뽕, 우동/면류)",
}

BUDGET_TIER_LABELS = {
    "budget": "가성비 (8,000원 이하 메뉴 우선 추천)",
    "flexible": "가격 상관없음 (만족도와 취향 최적화 우선)",
}


def _infer_menu_and_price(
    restaurant: Dict[str, Any], preference: UserPreferenceRequest
) -> Dict[str, str]:
    """폴백 추천 시 식당 카테고리와 사용자 조건에 맞는 대표 메뉴와 예상 가격을 생성합니다."""
    name = restaurant.get("place_name", "")
    category = restaurant.get("category_name", "")
    hints = restaurant.get("menu_hints", "")
    is_budget = preference.budget_tier == "budget"

    if "봉구스" in name or "밥버거" in category:
        return {
            "menu": "제육밥버거 + 컵라면" if is_budget else "치즈닭갈비 밥버거 세트",
            "price": "5,800원" if is_budget else "6,500원",
        }
    if "맘스터치" in name or "햄버거" in category or "패스트푸드" in category:
        return {
            "menu": "싸이버거 단품 + 콜라" if is_budget else "싸이버거 세트",
            "price": "6,800원" if is_budget else "7,300원",
        }
    if "이삭토스트" in name or "토스트" in category or "샌드위치" in category:
        return {
            "menu": "햄치즈 스페셜 토스트",
            "price": "3,900원",
        }
    if "담소" in name or "순대" in name or "국밥" in category or "육개장" in name:
        return {
            "menu": "돈사골 순대국" if is_budget else "우사골 순대국 정식",
            "price": "7,900원" if is_budget else "8,900원",
        }
    if "샐러디" in name or "샐러드" in category or "포케" in category:
        if preference.texture_temp == "rice":
            return {
                "menu": "칠리베이컨 웜볼" if is_budget else "우삼겹 웜볼",
                "price": "7,900원" if is_budget else "8,900원",
            }
        return {
            "menu": "멕시칸 랩 샌드위치" if is_budget else "칠리베이컨 웜볼",
            "price": "7,500원" if is_budget else "7,900원",
        }
    if "한솥" in name or "도시락" in category:
        return {
            "menu": "빅치킨마요 덮밥",
            "price": "4,900원",
        }
    if "홍콩반점" in name or "중식" in category or "짬뽕" in category:
        return {
            "menu": "얼큰 짬뽕" if preference.texture_temp == "soup" else "짜장면",
            "price": "7,500원" if preference.texture_temp == "soup" else "6,500원",
        }
    if hints:
        first_hint = hints.split("/")[0].strip()
        return {"menu": first_hint, "price": "7,500원" if is_budget else "9,000원"}

    if preference.texture_temp == "soup":
        return {"menu": "따뜻한 시그니처 국물 메뉴", "price": "7,800원" if is_budget else "9,500원"}
    if preference.texture_temp == "bread":
        return {"menu": "시그니처 버거/샌드위치", "price": "7,200원" if is_budget else "8,800원"}
    return {"menu": "오늘의 추천 한 그릇 정식", "price": "7,900원" if is_budget else "9,500원"}


def _score_restaurant(
    restaurant: Dict[str, Any],
    preference: UserPreferenceRequest,
    weather_info: Dict[str, Any],
) -> int:
    """폴백 추천 시 3-Tap 조건 및 날씨와의 적합도를 점수화합니다."""
    text = f"{restaurant.get('place_name', '')} {restaurant.get('category_name', '')} {restaurant.get('menu_hints', '')}"
    score = 0

    if preference.meal_mode == "quick":
        if any(k in text for k in ["버거", "토스트", "밥버거", "도시락", "분식", "김밥", "패스트푸드"]):
            score += 45
    elif preference.meal_mode == "proper":
        if any(k in text for k in ["한식", "국밥", "순대", "육개장", "도시락", "중식", "정식", "백반"]):
            score += 45
    elif preference.meal_mode == "clean":
        if any(k in text for k in ["샐러디", "샐러드", "포케", "랩"]):
            score += 65
        elif any(k in text for k in ["토스트", "샌드위치"]):
            score += 30

    if preference.texture_temp == "bread":
        if any(k in text for k in ["버거", "햄버거", "토스트", "샌드위치", "빵", "랩"]):
            score += 35
    elif preference.texture_temp == "rice":
        if any(k in text for k in ["밥", "도시락", "국밥", "덮밥", "한식", "순대", "웜볼", "포케"]):
            score += 35
    elif preference.texture_temp == "soup":
        if any(k in text for k in ["국", "육개장", "짬뽕", "면", "우동", "라면", "탕", "찌개"]):
            score += 35

    if weather_info.get("is_cold") and any(k in text for k in ["국", "육개장", "짬뽕", "따뜻", "웜볼", "토스트"]):
        score += 12

    if preference.budget_tier == "budget":
        if any(k in text for k in ["토스트", "밥버거", "도시락", "맘스터치", "김밥", "분식", "홍콩반점", "칠리베이컨", "랩"]):
            score += 15

    try:
        dist = int(restaurant.get("distance", "500"))
    except (TypeError, ValueError):
        dist = 500
    score += max(0, 20 - dist // 50)
    return score


def _build_fallback_recommendation(
    preference: UserPreferenceRequest,
    weather_info: Dict[str, Any],
    restaurants: List[Dict[str, Any]],
) -> RecommendationResponse:
    """Gemini API 호출 불가 시에도 즉시 합리적인 Top 3 카드를 생성하는 안전 폴백 로직입니다."""
    sorted_rests = sorted(
        restaurants,
        key=lambda r: _score_restaurant(r, preference, weather_info),
        reverse=True,
    )
    selected = sorted_rests[:3]
    if not selected:
        selected = [
            {
                "place_name": "맘스터치 협성대점",
                "distance_walk": "도보 4분",
                "place_url": f"https://map.kakao.com/link/search/{quote('맘스터치 협성대점')}",
            }
        ]

    # 다양성 확보를 위해 3개 미만이면 남은 목록에서 채움
    while len(selected) < 3 and len(sorted_rests) > len(selected):
        selected.append(sorted_rests[len(selected)])

    # 리프레시 픽(3번째)에는 앞선 두 곳과 다른 분위기의 매장(예: 샐러디/토스트 등)을 우선 배치
    if len(sorted_rests) >= 4:
        used_names = {r["place_name"] for r in selected[:2]}
        refresh_candidates = [
            r for r in sorted_rests[2:]
            if r["place_name"] not in used_names
            and any(k in f"{r.get('place_name', '')} {r.get('category_name', '')}" for k in ["샐러드", "포케", "토스트", "샌드위치", "국", "밥"])
        ]
        if refresh_candidates:
            selected[2] = refresh_candidates[0]

    personas = ["[AI 최적 픽]", "[가성비/스피드 픽]", "[리프레시 픽]"]
    weather_str = weather_info.get("weather", "쌀쌀한 흐림")
    temp_str = weather_info.get("temp", "7℃")
    mode_short = {
        "quick": "15분 컷 간편식",
        "proper": "제대로 된 한 끼",
        "clean": "가볍고 클린한 식사",
    }.get(preference.meal_mode, "맞춤 식사")
    texture_short = {
        "bread": "빵·패티의 깔끔한 식감",
        "rice": "밥 중심의 든든한 포만감",
        "soup": "속까지 데워주는 국물·면",
    }.get(preference.texture_temp, "선호 식감")

    top3: List[RecommendationItem] = []
    for idx, rest in enumerate(selected[:3]):
        name = rest.get("place_name", "추천 식당")
        walk = rest.get("distance_walk", "도보 5분")
        place_url = rest.get("place_url") or f"https://map.kakao.com/link/search/{quote(name)}"
        inferred = _infer_menu_and_price(rest, preference)

        if idx == 0:
            reason = (
                f"{temp_str}의 {weather_str} 날씨에 요청하신 '{mode_short}'과 '{texture_short}' 조건을 가장 균형 있게 충족합니다.\n"
                f"{walk} 거리로 이동 동선이 짧아 의사결정 피로 없이 바로 만족스러운 식사가 가능합니다."
            )
        elif idx == 1:
            budget_note = "8,000원 이하 가성비 예산에 딱 맞고" if preference.budget_tier == "budget" else "합리적인 가격대와 빠른 회전율로"
            reason = (
                f"{budget_note} {walk} 내외로 빠르게 픽업·식사할 수 있는 효율 최강 픽입니다.\n"
                f"바쁜 일정 속에서도 '{inferred['menu']}'로 실패 없는 한 끼를 보장합니다."
            )
        else:
            reason = (
                f"같은 패턴의 메뉴 대신 가볍게 기분 전환을 할 수 있는 스마트 대안 픽입니다.\n"
                f"{temp_str} 날씨와 현재 동선({walk})을 고려해 부담 없이 즐기기 좋은 메뉴로 선정했습니다."
            )

        top3.append(
            RecommendationItem(
                rank=idx + 1,
                category_persona=personas[idx],
                restaurant_name=name,
                recommended_menu=inferred["menu"],
                estimated_price=inferred["price"],
                distance_walk=walk,
                ai_reason=reason,
                baemin_url=f"baemin://search?query={name}",
                kakao_map_url=place_url,
            )
        )

    return RecommendationResponse(
        current_weather=weather_str,
        temperature=temp_str,
        top3=top3,
    )


def generate_recommendations(
    preference: UserPreferenceRequest,
    weather_info: Dict[str, Any],
    restaurants: List[Dict[str, Any]],
) -> RecommendationResponse:
    """Gemini 3.8 Flash Structured Outputs를 사용해 Top 3 초개인화 식당 추천을 생성합니다."""
    api_key = os.getenv("GEMINI_API_KEY", "").strip()
    if not api_key:
        logger.warning("GEMINI_API_KEY가 비어 있어 폴백 추천을 반환합니다.")
        return _build_fallback_recommendation(preference, weather_info, restaurants)

    meal_desc = MEAL_MODE_LABELS.get(preference.meal_mode, preference.meal_mode)
    texture_desc = TEXTURE_TEMP_LABELS.get(preference.texture_temp, preference.texture_temp)
    budget_desc = BUDGET_TIER_LABELS.get(preference.budget_tier, preference.budget_tier)

    restaurants_json = json.dumps(restaurants[:12], ensure_ascii=False, indent=2)

    prompt = f"""당신은 직장인과 대학생의 식사 의사결정 피로(Decision Fatigue)를 없애주는 초개인화 AI 다이닝 에이전트 'Dishcision (디시즌)'입니다.
아래 사용자의 3-Tap 선택, 실시간 날씨, 그리고 현재 위치 주변 실제 식당 목록을 종합 추론(Rationale AI)하여 가장 완벽한 Top 3 추천을 반환하세요.

[사용자 3-Tap 선택]
1. 식사 모드: {meal_desc}
2. 식감/온도: {texture_desc}
3. 예산 조건: {budget_desc}

[현재 날씨 정보]
- 날씨 상태: {weather_info.get("weather", "쌀쌀한 흐림")}
- 현재 기온: {weather_info.get("temp", "7℃")}
- 추위 여부(is_cold): {weather_info.get("is_cold", True)}

[주변 식당 목록 (카카오 로컬 데이터)]
{restaurants_json}

[필수 출력 규칙]
1. 반드시 위 [주변 식당 목록]에 있는 식당 중 서로 다른 3곳을 선정하여 rank 1, 2, 3으로 구성하세요.
2. 각 순위별 category_persona는 정확히 다음 3가지를 순서대로 부여하세요:
   - rank 1: "[AI 최적 픽]" (사용자 3-Tap 조건과 현재 날씨에 가장 부합하는 최고의 선택)
   - rank 2: "[가성비/스피드 픽]" (예산 절약 및 빠른 회전율/가까운 도보 거리 중심의 실속 선택)
   - rank 3: "[리프레시 픽]" (조건을 해치지 않으면서 기분 전환이나 신선한 밸런스를 제공하는 대안)
3. restaurant_name과 distance_walk, kakao_map_url은 위 목록의 값을 정확히 사용하세요.
4. recommended_menu와 estimated_price(예: "7,300원")는 해당 식당에서 실제 판매할 법한 구체적인 메뉴와 합리적 가격을 제시하세요. 특히 예산 조건이 'budget'이면 8,000원 이하 조합을 우선 추천하세요.
5. ai_reason은 반드시 한국어로, 현재 기온/날씨 + 3-Tap 조건 + 도보 이동 편의를 자연스럽게 엮은 설득력 있는 선정 근거 2줄(두 문장)로 작성하세요.
6. baemin_url은 반드시 "baemin://search?query=" + 식당명 형태로 작성하세요.
7. current_weather는 "{weather_info.get("weather", "쌀쌀한 흐림")}", temperature는 "{weather_info.get("temp", "7℃")}"로 설정하세요.
"""

    try:
        client = genai.Client(
            api_key=api_key,
            http_options=types.HttpOptions(
                timeout=20000,
                retry_options=types.HttpRetryOptions(attempts=1),
            ),
        )
        response = client.models.generate_content(
            model=GEMINI_MODEL,
            contents=prompt,
            config=types.GenerateContentConfig(
                response_mime_type="application/json",
                response_schema=RecommendationResponse,
                temperature=0.4,
                thinking_config=types.ThinkingConfig(
                    thinking_level=types.ThinkingLevel.LOW
                ),
            ),
        )

        parsed = getattr(response, "parsed", None)
        if isinstance(parsed, RecommendationResponse):
            result = parsed
        elif parsed is not None:
            result = RecommendationResponse.model_validate(parsed)
        else:
            result = RecommendationResponse.model_validate_json(response.text)

        # 식당 목록 매핑 테이블로 URL 및 필드 일관성 보정
        rest_by_name = {r.get("place_name", ""): r for r in restaurants}
        required_personas = ["[AI 최적 픽]", "[가성비/스피드 픽]", "[리프레시 픽]"]

        normalized_items: List[RecommendationItem] = []
        for idx, item in enumerate(result.top3[:3]):
            matched = rest_by_name.get(item.restaurant_name, {})
            kakao_url = (
                matched.get("place_url")
                or item.kakao_map_url
                or f"https://map.kakao.com/link/search/{quote(item.restaurant_name)}"
            )
            walk = matched.get("distance_walk") or item.distance_walk or "도보 5분"
            persona = item.category_persona or required_personas[idx]
            if persona not in required_personas:
                persona = required_personas[idx]

            normalized_items.append(
                RecommendationItem(
                    rank=idx + 1,
                    category_persona=persona,
                    restaurant_name=item.restaurant_name,
                    recommended_menu=item.recommended_menu,
                    estimated_price=item.estimated_price,
                    distance_walk=walk,
                    ai_reason=item.ai_reason,
                    baemin_url=f"baemin://search?query={item.restaurant_name}",
                    kakao_map_url=kakao_url,
                )
            )

        if len(normalized_items) < 3:
            logger.warning("Gemini 응답 항목이 3개 미만이어서 폴백으로 보완합니다.")
            return _build_fallback_recommendation(preference, weather_info, restaurants)

        return RecommendationResponse(
            current_weather=weather_info.get("weather", result.current_weather),
            temperature=weather_info.get("temp", result.temperature),
            top3=normalized_items,
        )

    except Exception as exc:
        logger.warning(
            "Gemini 3.8 Flash 호출 실패(%s)로 인해 스마트 폴백 추천을 반환합니다.", exc
        )
        return _build_fallback_recommendation(preference, weather_info, restaurants)
