from pathlib import Path
from typing import Any, Dict

import uvicorn
from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse

from backend.schemas import RecommendationResponse, UserPreferenceRequest
from backend.services.ai_engine import generate_recommendations
from backend.services.kakao_service import (
    KakaoServiceError,
    get_address_from_coords,
    get_nearby_restaurants,
    search_location_candidates,
)
from backend.services.weather_service import get_current_weather, merge_weather_context

load_dotenv(Path(__file__).resolve().parent.parent / ".env")

app = FastAPI(
    title="MenuFit API",
    description="초개인화 AI 다이닝 에이전트 'MenuFit (메뉴핏)' 백엔드 API",
    version="2.0.0",
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
    """프론트엔드 단일 페이지 앱을 반환합니다 (모바일/데스크톱 브라우저 캐시 완전 차단 헤더 포함)."""
    if FRONTEND_INDEX.exists():
        return HTMLResponse(
            content=FRONTEND_INDEX.read_text(encoding="utf-8"),
            headers={
                "Cache-Control": "no-cache, no-store, must-revalidate, max-age=0",
                "Pragma": "no-cache",
                "Expires": "0",
            },
        )
    return {"service": "MenuFit API", "status": "running"}


@app.get("/health")
def health_check() -> Dict[str, str]:
    """서버 상태 확인 엔드포인트."""
    return {"status": "ok"}


@app.get("/api/address")
def read_address(
    lat: float = Query(default=37.212768, description="위도 (협성대 기본값)"),
    lon: float = Query(default=126.952380, description="경도 (협성대 기본값)"),
) -> Dict[str, str]:
    """좌표를 카카오 역지오코딩으로 변환해 한글 행정구역 주소를 반환합니다."""
    return {"address_name": get_address_from_coords(lat, lon)}


@app.get("/api/search-location")
def search_location(
    query: str = Query(..., min_length=1, description="검색할 지역/역/학교/건물명"),
) -> Dict[str, Any]:
    """GPS가 PC/IP 오차로 부정확할 때 사용자가 실제 기준 좌표를 직접 지정할 수 있도록 장소 목록을 반환합니다."""
    return {"results": search_location_candidates(query)}


@app.get("/api/weather")
def read_weather(
    lat: float = Query(default=37.212768, description="위도 (협성대 기본값)"),
    lon: float = Query(default=126.952380, description="경도 (협성대 기본값)"),
) -> Dict[str, Any]:
    """현재 위치의 실시간 날씨 정보를 반환합니다."""
    return get_current_weather(lat, lon)


@app.post("/api/recommend", response_model=RecommendationResponse)
def recommend_meals(request: UserPreferenceRequest) -> RecommendationResponse:
    """
    사용자의 위치(한글 역지오코딩)·식사 방식(도보 1km / 배달 3.5km 완전 격리)·3-Tap 조건과
    실제 카카오 식당 데이터를 기반으로 탄단지 수치화 정석 3개 + 리프레시 2개 AI 다이닝 리포트를 반환합니다.
    """
    address_name = get_address_from_coords(request.latitude, request.longitude)
    weather_info = merge_weather_context(
        request.latitude,
        request.longitude,
        client_weather=request.current_weather,
        client_temp=request.temperature,
        client_icon=request.weather_icon,
    )
    try:
        restaurants = get_nearby_restaurants(
            request.latitude,
            request.longitude,
            delivery_mode=request.delivery_mode,
            texture_temp=request.texture_temp,
            meal_mode=request.meal_mode,
        )
    except KakaoServiceError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc

    try:
        return generate_recommendations(
            request,
            weather_info,
            restaurants,
            address_name=address_name,
        )
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


if __name__ == "__main__":
    uvicorn.run("backend.main:app", host="0.0.0.0", port=8000, reload=False)
