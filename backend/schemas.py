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
        description="따옴표 인용 없이 방문자 평가를 AI가 종합해 정리한 외식 리뷰 1줄 요약 ('실사용 만족도' 등 IT·전자제품 어휘 금지, 예: '~라는 평가가 지배적이며 재방문 만족도가 높습니다.')",
    )
    why_this_spot: str = Field(
        ...,
        description=(
            "타 매장 비교('~대비')·가짜 %·미실측 중량 단정 및 블로그 클리셰('겉바속촉', '조화롭게 어우러져', '풍성한 식감', '선사합니다' 등) 전면 금지. "
            "토스/배민 스타일처럼 직관적이고 센스 있는 미식가 친구가 콕 집어주듯, 해당 음식 본연의 맛 포인트·식감·조리 킥을 1~2문장 펀치라인으로 작성 (selection_logic과 표현 중복 금지)"
        ),
    )
    protein_dv_percent: int = Field(
        ...,
        description="식약처 성인 1일 단백질 권장량 55g 기준 충족률(%) 정수 (백엔드가 protein_g 기반으로 round(protein_g/55*100) 수학 재계산)",
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
        description=(
            "블로그 클리셰 및 상단 why_this_spot 핵심 표현 재사용 금지. "
            "사용자의 3가지 조건(식감·템포·예산)이 왜 이 메뉴에 딱 맞는지 미식가 친구가 짚어주듯 직관적이고 감각적인 토스/배민 스타일 1줄 펀치라인으로 작성"
        ),
    )
    dinner_pairing_guide: str = Field(
        ...,
        description=(
            "'두부 샐러드', '닭가슴살' 같은 뻔한 특정 다이어트 메뉴 강요 및 과거형 전면 금지. "
            "오늘 점심으로 이 메뉴를 선택할 시 섭취하는 나트륨·유분·탄수화물 특성을 바탕으로, 저녁에 줄일 성분(짠 국물·기름진 육류/튀김·정제 탄수화물 등)과 채울 성분(수분·칼륨·식이섬유·단백질 등)을 짚어주는 실질적 영양 조율 가이드 1~2줄"
        ),
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
        ...,
        description="네이버 모바일 통합 검색 스마트플레이스·방문자 리뷰 직행 URL(https://m.search.naver.com/search.naver?query=...)",
    )


class RecommendationResponse(BaseModel):
    address_name: str
    current_weather: str
    temperature: str
    delivery_mode: str
    standards: List[RecommendationItem]
    refreshes: List[RecommendationItem]
