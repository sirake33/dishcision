from typing import List, Literal, Optional
from pydantic import BaseModel, Field


class UserPreferenceRequest(BaseModel):
    latitude: float = Field(default=37.2118, description="위도 (협성대 기본값)")
    longitude: float = Field(default=126.9765, description="경도")
    delivery_mode: str = Field(
        default="walk",
        description="'walk'(도보 방문) 또는 'delivery'(배달 주문)",
    )
    meal_mode: str = Field(
        ...,
        description="'quick'(간편 15분컷), 'proper'(든든한 한끼), 'clean'(가벼운 클린식)",
    )
    texture_temp: str = Field(
        ...,
        description="'bread'(빵/패티), 'rice'(밥/든든함), 'soup'(면/국물)",
    )
    budget_tier: str = Field(
        ...,
        description="'budget'(도보 8000원 이하), 'flexible'(도보 8000~13000원), 'min_order_exact'(배달 1인 최소주문 딱맞춤), 'generous_group'(배달 2인 이상 여유 세트)",
    )


class NutritionFacts(BaseModel):
    calories: int = Field(..., description="예상 칼로리 (kcal)")
    calories_per_person: Optional[int] = Field(
        None, description="2인 이상 다인 세트일 때 1인당 칼로리 (단품이면 None)"
    )
    carbs_g: int = Field(..., description="탄수화물 (g)")
    protein_g: int = Field(..., description="단백질 (g)")
    fat_g: int = Field(..., description="지방 (g)")
    nutrition_highlight: str = Field(..., description="탄단지 영양 밸런스 분석 1줄")


class AIAnalysisReport(BaseModel):
    review_keywords: List[str] = Field(
        ...,
        description="방문자 칭찬 키워드 해시태그 3개 (예: ['#불향가득_직화', '#푸짐한_고기양', '#혼밥편함'])",
    )
    visitor_review_summary: str = Field(
        ...,
        description="따옴표 인용 없이 방문자 평가를 AI가 종합해 정리한 객관적 1줄 요약 (예: '~라는 평가가 지배적이며 실사용 만족도가 높습니다.')",
    )
    why_this_spot: str = Field(
        ...,
        description="임의의 퍼센트(%) 숫자 없이 주변 인근 동종 식당들과 비교한 팩트 중심 서술형 우위 1~2줄",
    )
    food_coma_status: str = Field(
        ..., description="탄단지 비율 기반 식곤증 위험도 진단 ('안전', '적정', '주의')"
    )
    food_coma_desc: str = Field(
        ...,
        description="탄단지 밸런스 기반의 오후 식곤증/집중력 유지 예측 1줄",
    )
    selection_logic: str = Field(
        ...,
        description="확신의 픽 또는 반전 매력 픽으로 선정된 명쾌한 해설 1줄",
    )


# Gemini 3.8 Flash가 추론할 내부 구조 (식당명/거리는 AI가 직접 쓰지 않고 index로 선택)
class AISelectionItem(BaseModel):
    selected_index: int = Field(..., description="제공된 식당 후보군 리스트의 인덱스 번호")
    rank: int = Field(..., description="확신의 픽은 1~3, 반전 매력 픽은 1~2")
    persona_type: Literal["standard", "refresh"] = Field(
        ..., description="'standard'(확신의 픽) 또는 'refresh'(반전 매력 픽)"
    )
    category_persona: str = Field(
        ..., description="'[확신의 픽]' 또는 '[반전 매력 픽]'"
    )
    recommended_menu: str = Field(..., description="추천 대표 메뉴명")
    estimated_price: str = Field(..., description="예상 가격 (예: 9,500원)")
    nutrition: NutritionFacts
    report: AIAnalysisReport


class AISelectionResponse(BaseModel):
    standards: List[AISelectionItem] = Field(
        ..., description="사용자 조건에 100% 충실한 확신의 픽 1~3위 (총 3개)"
    )
    refreshes: List[AISelectionItem] = Field(
        ..., description="사용자 템포는 유지하되 카테고리를 비튼 반전 매력 픽 대안 1~2위 (총 2개)"
    )


# 배달 모드 전용 최소주문금액 & 부족 금액(Gap) 최적 조합 스펙
class DeliverySpec(BaseModel):
    min_order_price: str = Field(..., description="최소주문금액 (예: 13,000원)")
    shortfall_price: int = Field(..., description="단품 기준 부족 금액 (0이면 즉시 충족)")
    filler_recommendation: str = Field(
        ..., description="부족 금액 맞춤 사이드/음료 조합 또는 1km 이내 포장 대안 안내"
    )
    coupang_benefit: str = Field(..., description="쿠팡이츠 와우 무료배달 혜택 분석")


# 프론트엔드로 전달되는 최종 결과 모델
class RecommendationItem(BaseModel):
    rank: int
    persona_type: Literal["standard", "refresh"] = Field(
        ..., description="'standard'(확신의 픽) 또는 'refresh'(반전 매력 픽)"
    )
    category_persona: str
    restaurant_name: str
    recommended_menu: str
    estimated_price: str
    distance_m: int
    distance_display: str
    emoji: str = Field(..., description="푸드 이모지 엠블럼")
    nutrition: NutritionFacts
    report: AIAnalysisReport
    is_meal_kit: bool = Field(
        default=False,
        description="땅스부대찌개, 담꾹 등 가스레인지/냄비 조리가 필요한 매장이면 True",
    )
    clean_store_name: str
    delivery_spec: Optional[DeliverySpec] = None
    coupang_eats_url: str
    kakao_map_url: str
    naver_review_url: str = Field(
        ..., description="네이버 모바일 통합 검색(플레이스 카드 연동) URL"
    )


class RecommendationResponse(BaseModel):
    address_name: str
    current_weather: str
    temperature: str
    delivery_mode: str
    standards: List[RecommendationItem]
    refreshes: List[RecommendationItem]
