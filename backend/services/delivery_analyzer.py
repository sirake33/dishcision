import re
from typing import Any, Dict, List, Optional, Tuple
from urllib.parse import quote

# 브랜드/업종별 실제 쿠팡이츠 최소주문금액 기준 및 실판매 대표 사이드/토핑 메뉴 목록 (원)
BRAND_DELIVERY_PROFILES: List[Tuple[Tuple[str, ...], int, List[Tuple[str, int]]]] = [
    (
        ("봉구스", "밥버거"),
        9000,
        [
            ("치즈/계란 토핑 추가", 1500),
            ("컵라면(육개장)", 1800),
            ("캔음료(콜라/사이다)", 1800),
            ("떡갈비 사이드", 2500),
            ("용가리치킨(4p)+음료", 3500),
        ],
    ),
    (
        ("한솥",),
        9000,
        [
            ("해쉬포테이토/김", 1200),
            ("캔콜라/사이다", 1800),
            ("치킨 2조각", 2500),
            ("미니고로케(2p)", 2800),
            ("반찬 계란말이", 3000),
            ("미니 찹쌀탕수육", 3200),
        ],
    ),
    (
        ("본도시락", "도시락", "행컵", "컵밥", "밀플랜비"),
        10000,
        [
            ("계란후라이 토핑", 1200),
            ("캔음료", 1800),
            ("따뜻한 미소장국/미역국", 1800),
            ("미니 반찬/소시지 추가", 2800),
            ("매콤 닭강정(소)", 3800),
        ],
    ),
    (
        ("이삭", "에그2000", "에그드랍"),
        11000,
        [
            ("해쉬브라운", 2200),
            ("캔음료/아이스티", 2400),
            ("아메리카노", 2800),
            ("모짜렐라 치즈/베이컨 토핑", 1800),
            ("갈릭버터 감자튀김", 3500),
        ],
    ),
    (
        ("써브웨이", "서브웨이", "프린샌드위치", "샌드위치"),
        12000,
        [
            ("더블치즈/베이컨 추가", 1800),
            ("초코칩 쿠키 1개", 1500),
            ("웨지 포테이토", 2200),
            ("탄산음료(16oz)", 2200),
            ("수프(브로콜리체다/콘수프)", 3900),
            ("미니 랩/해쉬브라운", 3600),
        ],
    ),
    (
        ("노브랜드버거",),
        12000,
        [
            ("콜라/사이다(R)", 1800),
            ("감자튀김(R)", 2200),
            ("상하이 핑거포크(소)", 3200),
            ("어니언 도넛(4p)", 3400),
            ("치킨너겟(5p)", 3800),
        ],
    ),
    (
        ("맘스터치",),
        13000,
        [
            ("케이준양념감자(소)", 2200),
            ("콜라(M)", 2000),
            ("바삭크림치즈볼(4조각)", 3700),
            ("치킨텐더(2조각)", 3200),
            ("후라이드 순살(소)", 4500),
            ("할라피뇨 너겟(4조각)", 3500),
        ],
    ),
    (
        ("프랭크버거", "왓더버거"),
        13000,
        [
            ("프렌치프라이", 2500),
            ("탄산음료(R)", 2000),
            ("치즈스틱(2조각)", 2800),
            ("게살튀김(3조각)", 3800),
            ("바삭 텐더(3조각)", 4200),
        ],
    ),
    (
        ("버거킹", "맥도날드", "롯데리아", "버거", "수제버거"),
        13000,
        [
            ("너겟킹/치킨너겟(4조각)", 2600),
            ("어니언링/감자튀김(R)", 2700),
            ("21치즈스틱(2개)", 2800),
            ("제로콜라(R)", 2200),
            ("코울슬로+치즈프라이", 4900),
            ("바삭킹(4조각)", 5500),
        ],
    ),
    (
        ("포케", "샐러리아", "샐러드"),
        12000,
        [
            ("훈제란/수란 토핑", 1500),
            ("아보카도/크래미 토핑", 2200),
            ("콤부차/탄산수", 2800),
            ("닭가슴살 100g 추가", 3200),
            ("따뜻한 단호박/양송이 스프", 3800),
        ],
    ),
    (
        ("본죽", "죽"),
        12000,
        [
            ("반찬 추가(장조림/오징어초무침)", 2500),
            ("전통 식혜/매실차", 2800),
            ("감자고로케(2p)", 3500),
            ("한우사골 육개장 파우치", 5000),
        ],
    ),
    (
        ("김밥", "청년다방", "분식", "떡볶이"),
        13000,
        [
            ("치즈/튀김만두 사리", 2000),
            ("꼬마김밥/참치마요 추가", 3500),
            ("모둠튀김(소)", 3800),
            ("순대(소)/어묵탕", 4500),
            ("쿨피스/음료", 2000),
        ],
    ),
    (
        ("파리바게뜨", "베이커리", "빵"),
        12000,
        [
            ("에그타르트/소금빵", 2900),
            ("아이스 아메리카노", 3000),
            ("치즈베이글/샌드위치 추가", 4500),
            ("양송이/클램차우더 수프", 4800),
        ],
    ),
    (
        ("베트남", "인더비엣", "에머이", "쌀국수"),
        13000,
        [
            ("고기/면 사리 추가", 2500),
            ("짜조(2피스)", 3500),
            ("새우볼/춘권(4피스)", 4500),
            ("제로콜라/탄산음료", 2000),
            ("미니 월남쌈/가라아게", 5500),
        ],
    ),
    (
        ("마라탕", "탕화쿵푸", "라홍방"),
        13000,
        [
            ("우삼겹/양고기 토핑 추가", 3000),
            ("분모자/유부 사리", 2500),
            ("미니 꿔바로우(소)", 5500),
            ("빙홍차/음료", 2500),
        ],
    ),
    (
        ("미소야", "상상카츠", "최고당", "우동", "라멘", "돈까스", "돈가스", "면당포", "칼국수", "국수"),
        13000,
        [
            ("미니 유부초밥(2p)", 2500),
            ("새우튀김(2미)", 3500),
            ("감자고로케(2p)", 3200),
            ("미니우동/면사리 추가", 3800),
            ("캔음료", 2000),
        ],
    ),
    (
        ("시루향기", "현대옥", "콩나물국밥"),
        12000,
        [
            ("수란/김 추가", 1500),
            ("오징어 젓갈/반찬 추가", 2500),
            ("오징어 한마리 데침(반접시)", 4500),
            ("메밀전병(2줄)", 4500),
            ("캔음료", 2000),
        ],
    ),
    (
        ("장수소머리", "더진국", "신의주", "국밥", "해장국", "순대", "설렁탕"),
        14000,
        [
            ("공기밥/육수 추가", 1500),
            ("캔콜라/사이다", 2000),
            ("수육 맛보기(소)", 5000),
            ("찹쌀순대(소)", 5000),
            ("고기만두/김치만두(4알)", 4500),
        ],
    ),
    (
        ("김치찌개", "김찌로", "부대찌개", "순두부", "찌개", "구름계란덮밥", "덮밥", "비빔밥", "한식"),
        13000,
        [
            ("공기밥/라면사리 추가", 1500),
            ("계란후라이/치즈사리", 1800),
            ("계란말이(소)", 4500),
            ("스팸구이(4조각)", 3800),
            ("캔음료", 2000),
        ],
    ),
    (
        ("챠이챠이", "예빈", "짬뽕", "중식", "중국요리"),
        14000,
        [
            ("공기밥 추가", 1500),
            ("바삭 군만두(4개)", 3500),
            ("멘보샤(4조각)", 5500),
            ("미니 탕수육", 6500),
            ("음료(콜라/사이다)", 2000),
        ],
    ),
]

DEFAULT_DELIVERY_PROFILE: Tuple[int, List[Tuple[str, int]]] = (
    13000,
    [
        ("공기밥/토핑 추가", 1500),
        ("캔음료", 2000),
        ("미니 튀김/만두 사이드", 4000),
        ("인기 1인 사이드 메뉴", 5500),
    ],
)


def parse_price_int(price_text: str, default: int = 8000) -> int:
    """가격 문자열('9,500원', '8,000~10,000원')에서 정수 금액(원)을 안전 추출합니다."""
    matches = re.findall(r"\d[\d,]*", str(price_text or ""))
    candidates: List[int] = []
    for raw in matches:
        try:
            val = int(raw.replace(",", ""))
        except ValueError:
            continue
        if 1000 <= val <= 200000:
            candidates.append(val)
    if not candidates:
        return default
    return candidates[0]


def clean_store_search_name(place_name: str) -> str:
    """클립보드 복사 및 배달앱 검색 정확도를 높이기 위한 깔끔한 지점명 포함 상호를 정리합니다."""
    cleaned = re.sub(r"\s+", " ", str(place_name or "")).strip()
    return cleaned


def build_delivery_deep_links(place_name: str) -> Dict[str, str]:
    """
    쿠팡이츠 모바일 앱 스킴(`coupangeats://`) 및 검색용 상호명 딥링크 정보를 생성합니다.
    """
    clean_name = clean_store_search_name(place_name)
    encoded_name = quote(clean_name)

    coupang_eats_url = f"coupangeats://search?keyword={encoded_name}"
    return {
        "clean_store_name": clean_name,
        "coupang_eats_url": coupang_eats_url,
    }


def get_brand_delivery_profile(
    place_name: str, category_name: str, menu_name: str = ""
) -> Tuple[int, List[Tuple[str, int]]]:
    """상호/카테고리 기준 브랜드 최소주문금액(원)과 대표 사이드 목록을 반환합니다."""
    return _match_delivery_profile(place_name, category_name, menu_name)


def _match_delivery_profile(
    place_name: str, category_name: str, menu_name: str
) -> Tuple[int, List[Tuple[str, int]]]:
    text = f"{place_name} {category_name} {menu_name}"
    for keywords, min_order, sides in BRAND_DELIVERY_PROFILES:
        if any(kw in text for kw in keywords):
            return min_order, sides
    return DEFAULT_DELIVERY_PROFILE


def _solve_best_side_combo(
    sides: List[Tuple[str, int]], shortfall: int
) -> Tuple[List[Tuple[str, int]], int]:
    """부족 금액(shortfall) 이상을 최소 추가 지출로 충족하는 실제 사이드 조합을 계산합니다."""
    if shortfall <= 0:
        return [], 0

    sorted_sides = sorted(sides, key=lambda x: x[1])

    # 1) 단일 사이드로 깔끔히 해결되는 최적 후보 탐색
    single_fits = [item for item in sorted_sides if item[1] >= shortfall]
    best_pair_items: Optional[List[Tuple[str, int]]] = None
    best_pair_total: Optional[int] = None

    # 2) 서로 다른 2개 사이드 조합 탐색 (단품+사이드 초과 지출 최소화 비교)
    for i in range(len(sorted_sides)):
        for j in range(i + 1, len(sorted_sides)):
            total = sorted_sides[i][1] + sorted_sides[j][1]
            if total >= shortfall:
                if best_pair_total is None or total < best_pair_total:
                    best_pair_total = total
                    best_pair_items = [sorted_sides[i], sorted_sides[j]]

    best_single = single_fits[0] if single_fits else None
    if best_single and best_pair_items and best_pair_total is not None:
        if best_single[1] <= best_pair_total + 300:
            return [best_single], best_single[1]
        return best_pair_items, best_pair_total
    if best_single:
        return [best_single], best_single[1]
    if best_pair_items and best_pair_total is not None:
        return best_pair_items, best_pair_total

    # 3) 부족 금액이 2개 합보다 큰 극단 케이스는 최고가 사이드 + 음료/추가 조합으로 안전 충족
    if sorted_sides:
        chosen = [sorted_sides[-1]]
        running = sorted_sides[-1][1]
        idx = len(sorted_sides) - 2
        while running < shortfall and idx >= 0:
            chosen.append(sorted_sides[idx])
            running += sorted_sides[idx][1]
            idx -= 1
        while running < shortfall:
            chosen.append(("인기 사이드 추가", 3000))
            running += 3000
        return chosen, running

    needed = max(shortfall, 2000)
    return [(f"사이드/음료 1~2종", needed)], needed


def analyze_delivery_spec(
    restaurant: Dict[str, Any],
    recommended_menu: str,
    estimated_price: str,
    *,
    distance_m: Optional[int] = None,
) -> Dict[str, Any]:
    """
    실제 배달앱 기준 매장별 최소주문금액, 추천 메뉴 가격 차액(Gap),
    실속 사이드 추가 조합(1km 이내 포장 대안 포함), 쿠팡이츠 와우 무료배달 분석을 반환합니다.
    """
    place_name = clean_store_search_name(restaurant.get("place_name", ""))
    category_name = str(restaurant.get("category_name", "")).strip()
    if distance_m is None:
        try:
            distance_m = int(float(str(restaurant.get("distance", "0")).strip()))
        except (TypeError, ValueError):
            distance_m = 0

    min_order_amount, sides = _match_delivery_profile(
        place_name, category_name, recommended_menu
    )
    menu_price_int = parse_price_int(estimated_price, default=8000)
    shortfall_amount = max(0, min_order_amount - menu_price_int)
    coupang_wow_benefit = "🚀 쿠팡이츠 와우 배달비 0원"

    if shortfall_amount == 0:
        min_order_solution = (
            "✅ 추가 사이드 없이 이 메뉴 단품만으로 최소주문금액을 즉시 충족합니다!"
        )
    else:
        combo_items, added_total = _solve_best_side_combo(sides, shortfall_amount)
        final_total = menu_price_int + added_total
        combo_desc = " + ".join(f"{name}({price:,}원)" for name, price in combo_items)
        min_order_solution = (
            f"'{combo_desc}' 추가 시 총 {final_total:,}원으로 최소주문금액 즉시 충족!"
        )
        if 0 <= distance_m <= 1000:
            min_order_solution += (
                f" (🚶 도보권({distance_m}m) 근거리 매장이므로 포장 픽업 시 {menu_price_int:,}원 그대로 배달비·최소주문 부담 0원)"
            )

    links = build_delivery_deep_links(place_name)

    return {
        "min_order_amount": min_order_amount,
        "min_order_price": f"{min_order_amount:,}원",
        "menu_price_int": menu_price_int,
        "shortfall_amount": shortfall_amount,
        "shortfall_price": shortfall_amount,
        "coupang_wow_benefit": coupang_wow_benefit,
        "coupang_benefit": coupang_wow_benefit,
        "min_order_solution": min_order_solution,
        "filler_recommendation": min_order_solution,
        **links,
    }
