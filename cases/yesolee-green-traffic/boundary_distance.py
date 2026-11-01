"""측정소별 녹색교통지역 경계 최단거리 계산 (수동 점검 ①: 경계 거리).

녹색교통지역 = 한양도성 내부(16.7㎢). 경계는 한양도성 성곽 라인으로,
사대문·사소문 8개 지점을 꼭짓점으로 하는 다각형으로 근사한다.
각 측정소가 이 경계에서 얼마나 떨어져 있는지(구역 내부/외부 포함)를 계산한다.

꼭짓점 좌표 출처: 위키백과 각 문화재 문서(소수점 십진수).
  숭례문 https://ko.wikipedia.org/wiki/숭례문
  흥인지문 https://ko.wikipedia.org/wiki/흥인지문
  숙정문 https://en.wikipedia.org/wiki/Sukjeongmun
  돈의문 https://ko.wikipedia.org/wiki/돈의문
  광희문 https://ko.wikipedia.org/wiki/광희문
  혜화문 https://ko.wikipedia.org/wiki/혜화문
  소의문 https://ko.wikipedia.org/wiki/소의문
  창의문 https://en.wikipedia.org/wiki/Changuimun

측정소 좌표: data/raw/station_info.csv (fetch_station_coords.py로 각자 받는다).

사용법:
  python cases/yesolee-green-traffic/boundary_distance.py

주의: 성곽을 8개 지점으로 이은 다각형은 근사다. 실제 경계는 행정동 단위로 더 복잡하다.
km 단위 선별용 거리이며, 검정의 비기각처럼 한 숫자로 적합성을 확정하지 않는다.
"""

import csv
import math
from pathlib import Path

# 한양도성 성곽 근사 다각형. 북→시계방향으로 사대문·사소문을 잇는다. (위도, 경도)
BOUNDARY = [
    ("숙정문(북)", 37.59556, 126.98111),
    ("혜화문(동북)", 37.58794, 127.00393),
    ("흥인지문(동)", 37.57111, 127.00972),
    ("광희문(동남)", 37.564375, 127.010075),
    ("숭례문(남)", 37.55972, 126.97528),
    ("소의문(서남)", 37.56250, 126.97194),
    ("돈의문(서)", 37.56861, 126.96944),
    ("창의문(서북)", 37.5926139, 126.9665944),
]

# 측정소 분류(plan.yaml). 코드 → (집단, 비고)
GROUPS = {
    "111125": ("처치", ""),
    "111124": ("처치", ""),
    "111202": ("대조·핵심", ""),
    "111154": ("대조·핵심", ""),
    "111232": ("대조·핵심", ""),
    "111263": ("대조·핵심", ""),
    "111275": ("대조·추가", ""),
    "111312": ("대조·추가", ""),
    "111264": ("대조·추가", ""),
    "111242": ("대조·추가", ""),
    "111213": ("대조·추가", ""),
    "111122": ("제외·우회", "서울역 접근 관문"),
    "111162": ("제외·우회", "도심 접근로"),
    "111143": ("제외·우회", "자동차전용도로"),
    "111282": ("제외·자료", "2018 신설"),
}

CSV = Path(__file__).resolve().parent / "data" / "raw" / "station_info.csv"

# 위도·경도를 미터 평면으로 바꾸는 국소 등거리 근사(시 규모에서 오차 <0.1%).
LAT0 = 37.57
M_PER_DEG_LAT = 111_132.0
M_PER_DEG_LON = 111_320.0 * math.cos(math.radians(LAT0))


def to_xy(lat, lon):
    return ((lon - 126.99) * M_PER_DEG_LON, (lat - LAT0) * M_PER_DEG_LAT)


def seg_dist(p, a, b):
    """점 p에서 선분 ab까지의 최단거리(미터). 모두 (x, y)."""
    px, py = p
    ax, ay = a
    bx, by = b
    dx, dy = bx - ax, by - ay
    if dx == 0 and dy == 0:
        return math.hypot(px - ax, py - ay)
    t = ((px - ax) * dx + (py - ay) * dy) / (dx * dx + dy * dy)
    t = max(0.0, min(1.0, t))
    cx, cy = ax + t * dx, ay + t * dy
    return math.hypot(px - cx, py - cy)


def point_in_polygon(p, poly_xy):
    """ray casting으로 내부 여부 판정."""
    x, y = p
    inside = False
    n = len(poly_xy)
    for i in range(n):
        x1, y1 = poly_xy[i]
        x2, y2 = poly_xy[(i + 1) % n]
        if (y1 > y) != (y2 > y):
            xint = x1 + (y - y1) * (x2 - x1) / (y2 - y1)
            if x < xint:
                inside = not inside
    return inside


def boundary_distance_km(lat, lon, poly_xy):
    p = to_xy(lat, lon)
    d = min(seg_dist(p, poly_xy[i], poly_xy[(i + 1) % len(poly_xy)]) for i in range(len(poly_xy)))
    inside = point_in_polygon(p, poly_xy)
    return d / 1000.0, inside


def main():
    poly_xy = [to_xy(lat, lon) for _, lat, lon in BOUNDARY]
    rows = list(csv.DictReader(CSV.open(encoding="utf-8")))

    out = []
    for r in rows:
        code = r["station_code"]
        dist_km, inside = boundary_distance_km(float(r["lat"]), float(r["lon"]), poly_xy)
        grp, note = GROUPS.get(code, ("?", ""))
        out.append((grp, dist_km, inside, r["station_name"], code, note))

    # 집단 순서 → 거리 순 정렬
    order = {"처치": 0, "대조·핵심": 1, "대조·추가": 2, "제외·우회": 3, "제외·자료": 4, "?": 9}
    out.sort(key=lambda x: (order[x[0]], x[1]))

    print(f"경계: 한양도성 8개 지점 근사 다각형 | 측정소 {len(out)}곳\n")
    print(f"{'집단':<10} {'측정소':<12} {'경계 최단거리':>10}  {'위치':<6} 비고")
    print("-" * 64)
    for grp, dist_km, inside, name, _code, note in out:
        loc = "내부" if inside else "외부"
        print(f"{grp:<10} {name:<12} {dist_km:>8.2f}km  {loc:<6} {note}")


if __name__ == "__main__":
    main()
