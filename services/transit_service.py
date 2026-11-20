"""조회 서비스: 버스/지하철 API 병렬 호출 → 파싱 → 방향 필터링 → 정렬."""
from __future__ import annotations

import logging
import re
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from datetime import datetime
from typing import Callable, TypeVar

from api import bus_api, subway_api
from api.errors import ApiError
from config import settings as cfg
from config.settings import Settings
from models.bus import BusInfo
from models.subway import SubwayInfo, TrainPosition

log = logging.getLogger(__name__)
T = TypeVar("T")


@dataclass
class QueryResult:
    queried_at: datetime
    bus: BusInfo | None
    bus_error: str | None
    subway: SubwayInfo | None
    subway_error: str | None
    is_mock: bool = False


def now_kst() -> datetime:
    return datetime.now(cfg.KST)


# ---------------------------------------------------------------------------
# 지하철 방향/노선 필터
# ---------------------------------------------------------------------------
def stations_until_gasan(station_id: str) -> int | None:
    """현재 역에서 가산디지털단지까지 남은 역 수. 가산으로 오는 경로(경원선~서울~구로)가 아니면 None.

    '상행/하행' 문자열이 아니라 실제 역 위치로 판단한다.
    경인선(구로 이후 오류동·부평 방면)이나 가산 이남 역은 None.
    """
    if station_id == cfg.SUBWAY_STATION_ID:
        return 0
    if (len(station_id) == 10 and station_id.startswith(cfg.SUBWAY_APPROACH_PREFIX)
            and station_id[-3:].isdigit()):
        n = int(station_id[-3:])
        if cfg.SUBWAY_APPROACH_MIN <= n <= cfg.SUBWAY_APPROACH_LAST:
            return cfg.SUBWAY_APPROACH_LAST + 1 - n
    return None


def estimate_remaining_sec(stations_away: int, age_sec: int | None) -> int | None:
    """소요시간 표(사용자 실측) 기반 예상 남은 시간. 위치가 확인된 뒤 지난 시간만큼 뺀다.

    표에 없는 거리(13역 이상)나 위치 시각을 모르면 None (추정하지 않음).
    """
    minutes = cfg.SUBWAY_TRAVEL_MIN_BY_STATIONS.get(stations_away)
    if minutes is None or age_sec is None:
        return None
    return max(0, minutes * 60 - age_sec)


def normalize_station_name(name: str) -> str:
    name = re.sub(r"\(.*?\)", "", name).strip()   # "쌍용(나사렛대)" → "쌍용"
    return name[:-1] if name.endswith("역") and len(name) > 2 else name


def filter_and_sort_subway(trains: list[TrainPosition], now: datetime) -> tuple[list[TrainPosition], list[str]]:
    """가산디지털단지에서 독산 방면으로 탈 수 있는 1호선 열차만 남기고 가까운 순으로 정렬.

    조건:
      1) 1호선 & 하행
      2) 현재 위치가 가산으로 들어오는 경로 위 (또는 가산에 진입/도착 중)
      3) 행선지가 가산 이남 역 (구로행·인천행·광운대행 등은 가산에 오지 않음)
      4) 개인 제외 행선지(광명·서동탄 등) 제외
    급행은 독산에 서지 않지만 가산에는 정차하므로 동일하게 표시한다.
    """
    selected: list[TrainPosition] = []
    for t in trains:
        if t.subway_id != cfg.SUBWAY_LINE_ID or t.updn_line != cfg.SUBWAY_SOUTHBOUND_UPDN:
            continue
        away = t.stations_away if t.from_arrival_api else stations_until_gasan(t.station_id)
        if away is None:
            continue
        dest = normalize_station_name(t.destination)
        if dest not in cfg.SOUTHBOUND_DESTINATIONS or dest in cfg.EXCLUDED_DESTINATIONS:
            continue

        age = int((now - t.generated_at).total_seconds()) if t.generated_at else None
        if age is not None and age < 0:
            age = 0
        if away == 0:
            # 가산에서 이미 출발했거나, 진입/도착 정보가 오래돼 떠났을 것이 확실한 열차는 숨김
            if t.status_code in ("2", "3"):
                continue
            if age is None or age > cfg.SUBWAY_AT_STATION_MAX_AGE:
                continue

        t.stations_away = away
        t.age_sec = age
        t.stale = age is None or age > cfg.SUBWAY_STALE_AFTER_SEC
        t.est_remaining_sec = estimate_remaining_sec(away, age)
        selected.append(t)

    selected.sort(key=lambda t: (t.stations_away, -(t.generated_at.timestamp() if t.generated_at else 0)))
    warnings: list[str] = []
    if not selected:
        warnings.append("현재 가산디지털단지역으로 오는 독산 방면 1호선 열차가 없습니다.")
    return selected[: cfg.SUBWAY_MAX_ROWS], warnings


# ---------------------------------------------------------------------------
# 서비스
# ---------------------------------------------------------------------------
class TransitService:
    def __init__(self, settings: Settings):
        self.settings = settings

    def query(self) -> QueryResult:
        if self.settings.mock_mode:
            from services import mock_data
            time.sleep(0.6)  # 로딩 표시 확인용
            return mock_data.build_mock_result(now_kst())

        with ThreadPoolExecutor(max_workers=2, thread_name_prefix="api") as ex:
            fb = ex.submit(_safe, self.query_bus, "bus")
            fs = ex.submit(_safe, self.query_subway, "subway")
            bus, bus_err = fb.result()
            subway, subway_err = fs.result()
        return QueryResult(now_kst(), bus, bus_err, subway, subway_err)

    def query_bus(self) -> BusInfo:
        data = bus_api.fetch_bus_raw(self.settings.bus_api_key)
        return bus_api.parse_bus_response(data, now_kst())

    def query_subway(self) -> SubwayInfo:
        with ThreadPoolExecutor(max_workers=1, thread_name_prefix="api-arrival") as ex:
            fa = ex.submit(self._query_arrival_trains)
            data = subway_api.fetch_subway_raw(self.settings.subway_api_key)
            trains = subway_api.parse_subway_response(data)
            trains = merge_missing_trains(trains, fa.result())
        selected, warnings = filter_and_sort_subway(trains, now_kst())
        return SubwayInfo(cfg.SUBWAY_STATION_NAME, cfg.SUBWAY_DIRECTION_LABEL, selected, warnings=warnings)

    def _query_arrival_trains(self) -> list[TrainPosition]:
        """보조 조회. 실패해도 위치 API 결과만으로 화면을 그린다."""
        try:
            return subway_api.parse_arrival_response(subway_api.fetch_arrival_raw(self.settings.subway_api_key))
        except ApiError as e:
            log.warning("subway-arrival: %s (%s)", e.message, e.kind.value)
        except Exception:
            log.exception("subway-arrival: unexpected error")
        return []


def merge_missing_trains(positions: list[TrainPosition], arrivals: list[TrainPosition]) -> list[TrainPosition]:
    """위치 API 에 없는 열차(열차번호 기준)만 도착정보 API 에서 가져와 덧붙인다."""
    known = {t.train_no for t in positions if t.train_no}
    extra = [t for t in arrivals if t.train_no and t.train_no not in known]
    if extra:
        log.info("subway: %d train(s) missing from position API, filled from arrival API: %s",
                 len(extra), ", ".join(f"{t.train_no}({t.destination})" for t in extra))
    return positions + extra


def _safe(fn: Callable[[], T], label: str) -> tuple[T | None, str | None]:
    """한쪽 API 실패가 다른 쪽에 영향을 주지 않도록 결과/오류를 분리해 반환."""
    try:
        return fn(), None
    except ApiError as e:
        log.warning("%s: %s (%s)", label, e.message, e.kind.value)
        return None, e.message
    except Exception:
        log.exception("%s: unexpected error", label)
        return None, "알 수 없는 오류가 발생했습니다. 잠시 후 다시 조회해 주세요."
