"""에어코리아 측정소 정보 API로 분석 대상 측정소의 좌표를 받아 저장한다.

경계 최단거리(수동 점검 ①)에 쓸 측정소 위도·경도를 수집하는 일회성 스크립트다.
인증키는 환경변수 AIRKOREA_KEY로 받아 코드·출력·저장 파일에 남기지 않는다.

사용법:
  export AIRKOREA_KEY='발급받은_Decoding_인증키'
  python cases/yesolee-green-traffic/fetch_station_coords.py

결과: data/raw/station_info.csv (station_name, station_code, addr, lat, lon)
원자료이므로 커밋하지 않는다.
"""

import csv
import os
import sys
from pathlib import Path
from urllib.parse import unquote

import requests

# 대기오염 측정소 정보 조회 서비스 - 측정소 목록. ver>=1.1 이어야 dmX·dmY 좌표가 온다.
# 베이스 엔드포인트 뒤에 작업명 getMsrstnList를 붙인다.
ENDPOINT = "https://apis.data.go.kr/B552584/MsrstnInfoInqireSvc/getMsrstnList"

# plan.yaml에서 정한 분석 대상 15곳. 이름은 API 응답과 공백을 무시하고 맞춘다.
TARGETS = {
    "111125": "종로",            # 처치
    "111124": "청계천로",        # 처치
    "111202": "신촌로",          # 대조(핵심)
    "111154": "홍릉로",          # 대조(핵심)
    "111232": "영등포로",        # 대조(핵심)
    "111263": "도산대로",        # 대조(핵심)
    "111275": "천호대로",        # 대조(추가)
    "111312": "화랑로",          # 대조(추가)
    "111264": "강남대로",        # 대조(추가)
    "111242": "동작대로중앙차로",  # 대조(추가)
    "111213": "공항대로",        # 대조(추가)
    "111122": "한강대로",        # 제외(우회·확산 별도 확인)
    "111162": "정릉로",          # 제외(우회·확산 별도 확인)
    "111143": "강변북로",        # 제외(자동차전용도로)
    "111282": "시흥대로",        # 제외(자료 길이)
}

OUT = Path(__file__).resolve().parent / "data" / "raw" / "station_info.csv"


def norm(name: str) -> str:
    """측정소명 비교용: 공백 제거."""
    return "".join((name or "").split())


def main() -> int:
    key = os.environ.get("AIRKOREA_KEY")
    if not key:
        print("환경변수 AIRKOREA_KEY가 없습니다. 발급받은 인증키를 넣어 주세요.")
        print("  export AIRKOREA_KEY='...'")
        return 1

    # Encoding/Decoding 키를 모두 받도록 한 번 디코드한 뒤 requests가 한 번만 인코딩하게 한다.
    # (Encoding 키를 그대로 params로 넘기면 %가 다시 인코딩돼 인증이 깨진다.)
    key = unquote(key)

    params = {
        "serviceKey": key,
        "returnType": "json",
        "numOfRows": "1000",
        "pageNo": "1",
        "addr": "서울",   # 서울 측정소만
        "ver": "1.1",      # 좌표(dmX·dmY) 포함
    }
    # data.go.kr 게이트웨이가 기본 User-Agent를 막는 경우가 있어 명시한다.
    headers = {"User-Agent": "policy-effect-analytics/fetch_station_coords"}
    resp = requests.get(ENDPOINT, params=params, headers=headers, timeout=30)

    if resp.status_code != 200:
        # 서버가 보낸 실제 사유를 보여 준다. 키 노출을 피해 URL은 찍지 않는다.
        print(f"HTTP {resp.status_code}. 서버 응답 본문:")
        print(resp.text[:800])
        print("\n점검: ① 인증키 활용신청이 '승인'됐는지 ② Decoding/Encoding 키를 바꿔 다시 시도"
              " ③ 발급 직후면 수십 분~1시간 대기 후 재시도")
        return 2

    try:
        body = resp.json()["response"]["body"]
    except Exception:
        # 키 오류 등은 보통 XML 오류 메시지로 온다. 앞부분만 보여 준다.
        print("JSON 파싱 실패. 응답 앞부분:")
        print(resp.text[:800])
        return 2

    items = body.get("items") or []
    print(f"API 응답 측정소 수(서울): {len(items)}")
    if items:
        print("첫 항목 필드:", list(items[0].keys()))

    # 이름으로 조회 (코드가 응답에 없을 수 있어 이름 매칭을 기본으로 한다)
    by_name = {norm(it.get("stationName", "")): it for it in items}

    rows = []
    missing = []
    for code, name in TARGETS.items():
        it = by_name.get(norm(name))
        if not it:
            missing.append(f"{name}({code})")
            continue
        # dmX·dmY 중 위도(~37)·경도(~127)를 값 범위로 구분한다.
        a, b = _to_float(it.get("dmX")), _to_float(it.get("dmY"))
        lat, lon = _assign_latlon(a, b)
        rows.append(
            {
                "station_name": name,
                "station_code": code,
                "addr": it.get("addr", ""),
                "lat": lat,
                "lon": lon,
            }
        )

    OUT.parent.mkdir(parents=True, exist_ok=True)
    with OUT.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=["station_name", "station_code", "addr", "lat", "lon"])
        w.writeheader()
        w.writerows(rows)

    print(f"\n저장: {OUT}  ({len(rows)}곳)")
    for r in rows:
        print(f"  {r['station_code']} {r['station_name']:<10} lat={r['lat']} lon={r['lon']}")
    if missing:
        print("\n⚠️ 이름으로 못 찾은 측정소:", ", ".join(missing))
        print("   API의 측정소명 표기가 다를 수 있습니다. 응답 이름을 확인해 TARGETS를 맞춰 주세요.")
    return 0


def _to_float(v):
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def _assign_latlon(a, b):
    """두 좌표값을 범위로 위도·경도에 배정한다. 서울 위도≈37.x, 경도≈126~127.x."""
    for lat, lon in ((a, b), (b, a)):
        if lat is not None and lon is not None and 37.0 <= lat <= 38.0 and 126.0 <= lon <= 128.0:
            return lat, lon
    return a, b  # 범위를 못 맞추면 원값 그대로 두고 사람이 확인


if __name__ == "__main__":
    sys.exit(main())
