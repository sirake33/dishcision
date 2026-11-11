from pathlib import Path
from typing import Any, Dict

import uvicorn
from dotenv import load_dotenv
from fastapi import FastAPI, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse

from backend.schemas import RecommendationResponse, UserPreferenceRequest
from backend.services.ai_engine import generate_recommendations
from backend.services.kakao_service import get_nearby_restaurants
from backend.services.weather_service import get_current_weather

load_dotenv(Path(__file__).resolve().parent.parent / ".env")

app = FastAPI(
    title="Dishcision API",
    description="초개인화 AI 다이닝 에이전트 'Dishcision (디시즌)' 백엔드 API",
    version="1.0.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

FRONTEND_INDEX = Path(__file__).resolve().parent.parent / "frontend" / "index.html"


@app.get("/")
def serve_frontend():
    """프론트엔드 단일 페이지 앱을 반환합니다."""
    if FRONTEND_INDEX.exists():
        return FileResponse(FRONTEND_INDEX)
    return {"service": "Dishcision API", "status": "running"}


@app.get("/health")
def health_check() -> Dict[str, str]:
    """서버 상태 확인 엔드포인트."""
    return {"status": "ok"}


@app.get("/api/weather")
def read_weather(
    lat: float = Query(default=37.2118, description="위도"),
    lon: float = Query(default=126.9765, description="경도"),
) -> Dict[str, Any]:
    """현재 위치의 실시간 날씨 정보를 반환합니다."""
    return get_current_weather(lat, lon)


@app.post("/api/recommend", response_model=RecommendationResponse)
def recommend_meals(request: UserPreferenceRequest) -> RecommendationResponse:
    """사용자의 3-Tap 선택과 날씨, 주변 식당 데이터를 기반으로 Gemini 3.8 Flash Top 3 추천을 반환합니다."""
    weather_info = get_current_weather(request.latitude, request.longitude)
    restaurants = get_nearby_restaurants(request.latitude, request.longitude)
    return generate_recommendations(request, weather_info, restaurants)


if __name__ == "__main__":
    uvicorn.run("backend.main:app", host="0.0.0.0", port=8000, reload=False)
