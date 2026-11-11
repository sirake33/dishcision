from typing import List
from pydantic import BaseModel, Field


class UserPreferenceRequest(BaseModel):
    latitude: float = Field(default=37.2118, description="위도 (기본값: 협성대 부근)")
    longitude: float = Field(default=126.9765, description="경도 (기본값: 협성대 부근)")
    meal_mode: str = Field(
        default="quick",
        description="식사 모드 ('quick': 간편 15분컷 햄버거/토스트/밥버거/분식, 'proper': 제대로된 한끼, 'clean': 샐러드/포케)",
    )
    texture_temp: str = Field(
        default="bread",
        description="식감/온도 ('bread': 빵/패티, 'rice': 밥/든든함, 'soup': 면/국물)",
    )
    budget_tier: str = Field(
        default="budget",
        description="예산 티어 ('budget': 8000원 이하 가성비, 'flexible': 무관)",
    )


class RecommendationItem(BaseModel):
    rank: int = Field(..., description="추천 순위 (1~3)")
    category_persona: str = Field(
        ...,
        description="추천 페르소나 ([AI 최적 픽], [가성비/스피드 픽], [리프레시 픽] 중 하나)",
    )
    restaurant_name: str = Field(..., description="식당명")
    recommended_menu: str = Field(..., description="추천 메뉴")
    estimated_price: str = Field(..., description="예상 가격 (예: 7,500원)")
    distance_walk: str = Field(..., description="도보 이동 시간 (예: 도보 4분)")
    ai_reason: str = Field(..., description="선정 근거 2줄")
    baemin_url: str = Field(..., description="배달의민족 딥링크 (baemin://search?query=식당명)")
    kakao_map_url: str = Field(..., description="카카오맵 링크")


class RecommendationResponse(BaseModel):
    current_weather: str = Field(..., description="현재 날씨 설명")
    temperature: str = Field(..., description="현재 기온 (예: 7℃)")
    top3: List[RecommendationItem] = Field(..., description="Top 3 AI 추천 카드 리스트")
