"""앱 설정.

조회 대상(금천07 / JNK디지털타워, 가산디지털단지역 1호선 독산 방면)은 개인용 고정값이다.
아래 ID 값들은 2026-11-20 실제 API 응답으로 검증했다. (README의 '검증 결과' 참고)
API KEY는 소스코드에 두지 않고 .env 파일에서 읽는다.
"""
from __future__ import annotations

import os
import sys
from dataclasses import dataclass
from datetime import timedelta, timezone
from pathlib import Path

from dotenv import dotenv_values

KST = timezone(timedelta(hours=9), "KST")

# ---------------------------------------------------------------------------
# 버스: 서울특별시_버스도착정보조회 서비스 (data.go.kr)
#   GET http://ws.bus.go.kr/api/rest/arrive/getArrInfoByRoute
#       ?serviceKey=&stId=&busRouteId=&ord=&resultType=json
# ---------------------------------------------------------------------------
BUS_API_URL = "http://ws.bus.go.kr/api/rest/arrive/getArrInfoByRoute"
BUS_ROUTE_NAME = "금천07"
BUS_ROUTE_ID = "117900007"        # 금천07 내부 노선 ID (getArrInfoByRouteAll 로 확인)
BUS_STATION_ARS_ID = "17635"      # 정류장 표시번호 (정류장 표지판 번호)
BUS_STATION_ID = "116900298"      # 정류소 내부 ID (stId) - arsId 와 다름
BUS_STATION_ORD = 27              # 금천07 노선상 JNK디지털타워 순번 (staOrd)
BUS_STATION_NAME = "JNK디지털타워"
# 금천07 노선상 17635 는 구로디지털단지역(25) → 구로디지털단지입구(26) → [JNK(27)]
# → 에이스하이엔드타워2차(28) → … → 가산디지털단지역3번출구(35) → 독산역(40) 순서로 정차.
# 즉 이 정류장은 '가산디지털단지역·독산역(시흥) 방면' 승차 정류장이다.
BUS_DIRECTION_LABEL = "가산디지털단지역 · 독산역 방면"
BUS_NEXT_STOP_NAME = "에이스하이엔드타워2차"

# ---------------------------------------------------------------------------
# 지하철: 서울시 지하철 실시간 열차 위치정보 (data.seoul.go.kr, realtimePosition)
#   GET http://swopenAPI.seoul.go.kr/api/subway/{KEY}/json/realtimePosition/0/{END}/1호선
#   (realtimeStationArrival 은 1호선 갱신이 늦고 2~3대만 줘서 사용하지 않음 - api/subway_api.py 참고)
# ---------------------------------------------------------------------------
SUBWAY_API_URL = "http://swopenAPI.seoul.go.kr/api/subway/{key}/json/realtimePosition/0/{end}/{line}"
SUBWAY_QUERY_LINE = "1호선"
# 보조: 역 도착정보 (realtimeStationArrival). 위치 API 가 일부 열차를 빠뜨리는 경우가 있어
# (2026-11-20 실측: 구로 도착 중인 0645 신창행이 위치 API 에 없음) 빠진 열차만 여기서 채운다.
SUBWAY_ARRIVAL_URL = "http://swopenAPI.seoul.go.kr/api/subway/{key}/json/realtimeStationArrival/0/30/{station}"
SUBWAY_ARRIVAL_STATION = "가산디지털단지"
SUBWAY_QUERY_END = 300
SUBWAY_LINE_ID = "1001"                 # 1호선
SUBWAY_STATION_ID = "1001080142"        # 가산디지털단지 (1호선)
SUBWAY_SOUTHBOUND_UPDN = "1"            # realtimePosition updnLine: 1 = 하행
# 가산으로 들어오는 하행 열차가 지나는 구간: 경원선~서울~구로 (1001000100 ~ 1001000141).
# 역 ID 끝 3자리가 가산 쪽으로 1씩 증가한다 (청량리 124, 서울 133, 영등포 139, 구로 141).
# 구로 이후 경인선(142~, 오류동·부평 방면)은 가산을 지나지 않으므로 제외.
SUBWAY_APPROACH_PREFIX = "1001000"
SUBWAY_APPROACH_MIN = 100
SUBWAY_APPROACH_LAST = 141              # 구로 = 가산 직전 역
SUBWAY_STATION_NAME = "가산디지털단지역"
SUBWAY_DIRECTION_LABEL = "독산 방면 (하행)"
SUBWAY_MAX_ROWS = 8
# 가산까지 남은 역 수 → 평소 소요시간(분). 사용자 실측 기준 (일반열차).
# API 가 도착 예정시간을 주지 않아 이 표로 '예상' 시간을 계산한다. 표에 없는 거리는 역 수만 표시.
SUBWAY_TRAVEL_MIN_BY_STATIONS = {
    1: 5,    # 구로
    2: 7,    # 신도림
    3: 10,   # 영등포
    4: 12,   # 신길
    5: 14,   # 대방
    6: 16,   # 노량진
    7: 20,   # 용산
    8: 22,   # 남영
    9: 25,   # 서울역
    10: 28,  # 시청
    11: 30,  # 종각
    12: 32,  # 종로3가
}
# 환승 예상: JNK디지털타워에서 버스를 탄 뒤 가산디지털단지역 승강장까지 걸리는 시간(분, 가정값).
BUS_TO_GASAN_MIN = 15
TRANSFER_TIGHT_SEC = 180                # 버스 도착과 열차 도착이 ±이 시간 안이면 '아슬아슬(△)'로 표시
SUBWAY_STALE_AFTER_SEC = 300          # 위치 정보가 이보다 오래되면 '정보 지연' 표시
SUBWAY_AT_STATION_MAX_AGE = 120         # 가산 진입/도착 정보가 이보다 오래되면 이미 출발한 것으로 보고 숨김

# 가산디지털단지역 남쪽(독산 방면)에 있는 1호선 종착 가능역.
# 이 목록에 있는 행선지면 '가산을 지나 독산 방면으로 간다'고 확신할 수 있다.
SOUTHBOUND_DESTINATIONS = frozenset({
    "독산", "금천구청", "광명", "석수", "관악", "안양", "명학", "금정", "군포", "당정",
    "의왕", "성균관대", "화서", "수원", "세류", "병점", "서동탄", "세마", "오산대", "오산",
    "진위", "송탄", "서정리", "평택지제", "지제", "평택", "성환", "직산", "두정", "천안",
    "봉명", "쌍용", "아산", "배방", "온양온천", "신창",
})
# 개인적으로 타지 않는 행선지
EXCLUDED_DESTINATIONS = frozenset({"광명", "서동탄", "병점", "수원"})

HTTP_TIMEOUT = (5, 10)   # (연결, 읽기) 초
STALE_AFTER_SEC = 120    # 데이터 생성 후 이 시간이 지나면 '갱신 지연'으로 표시


def app_dir() -> Path:
    """실행 파일(EXE) 또는 프로젝트 루트 폴더."""
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parent.parent


def resource_path(relative: str) -> Path:
    """PyInstaller 번들 내부 리소스(styles.qss 등) 경로."""
    base = Path(getattr(sys, "_MEIPASS", app_dir()))
    return base / relative


@dataclass(frozen=True)
class Settings:
    bus_api_key: str
    subway_api_key: str
    mock_mode: bool
    env_path: Path | None

    @property
    def secrets(self) -> list[str]:
        return [k for k in (self.bus_api_key, self.subway_api_key) if k]

    def missing_key_message(self) -> str | None:
        if self.mock_mode:
            return None
        missing = []
        if not self.bus_api_key:
            missing.append("SEOUL_BUS_API_KEY")
        if not self.subway_api_key:
            missing.append("SEOUL_SUBWAY_API_KEY")
        if not missing:
            return None
        where = str(self.env_path) if self.env_path else f"{app_dir() / '.env'}"
        return (f"API KEY가 설정되지 않았습니다: {', '.join(missing)}\n"
                f".env 파일({where})에 값을 입력한 뒤 프로그램을 다시 실행해 주세요.")


def _find_env_file() -> Path | None:
    for candidate in (app_dir() / ".env", Path.cwd() / ".env"):
        if candidate.is_file():
            return candidate
    return None


def _truthy(value: str | None) -> bool:
    return (value or "").strip().lower() in {"1", "true", "yes", "y", "on"}


def load_settings() -> Settings:
    env_path = _find_env_file()
    values = dict(dotenv_values(env_path)) if env_path else {}

    def get(name: str) -> str:
        # OS 환경변수가 .env 보다 우선
        return (os.environ.get(name) or values.get(name) or "").strip()

    def key(name: str) -> str:
        v = get(name)
        return "" if v.upper().startswith("YOUR_") else v

    return Settings(
        bus_api_key=key("SEOUL_BUS_API_KEY"),
        subway_api_key=key("SEOUL_SUBWAY_API_KEY"),
        mock_mode=_truthy(get("MOCK_MODE")),
        env_path=env_path,
    )
