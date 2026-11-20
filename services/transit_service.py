"""조회 서비스: 버스/지하철 API 병렬 호출 → 파싱 → 방향 필터링 → 정렬."""
from __future__ import annotations

import logging
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from typing import Callable, TypeVar

from api import bus_api, subway_api, timetable_api
from api.errors import ApiError
from config import settings as cfg
from config.settings import Settings
from models.bus import BusInfo
from api.timetable_api import ScheduledStop, train_number
from models.subway import GasanTrain, SubwayInfo, TrainPosition, normalize_station_name

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


def select_approaching_trains(trains: list[TrainPosition], now: datetime) -> list[TrainPosition]:
    """가산디지털단지에서 독산 방면으로 탈 수 있는, 아직 가산을 지나지 않은 1호선 열차 (실시간 위치).

    조건:
      1) 1호선 & 하행
      2) 현재 위치가 가산으로 들어오는 경로 위 (또는 가산에 진입/도착 중)
      3) 행선지가 가산 이남 역 (구로행·인천행·광운대행 등은 가산에 오지 않음)
      4) 개인 제외 행선지(광명·서동탄 등) 제외
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
        selected.append(t)

    selected.sort(key=lambda t: (t.stations_away, -(t.generated_at.timestamp() if t.generated_at else 0)))
    return selected


# ---------------------------------------------------------------------------
# 시간표 + 실시간 위치 → 가산 도착 예정 (모든 시각은 API 값에서만 계산)
# ---------------------------------------------------------------------------
def service_day(now: datetime) -> date:
    """운행일 (새벽 SERVICE_DAY_START_HOUR 시 전은 전날)."""
    return (now - timedelta(hours=cfg.SERVICE_DAY_START_HOUR)).date()


def week_tag(day: date) -> str:
    """시간표 API WEEK_TAG: 1 평일 / 2 토요일 / 3 일요일. (공휴일은 구분하지 않음)"""
    return {5: "2", 6: "3"}.get(day.weekday(), "1")


def at_day_sec(day: date, sec: int) -> datetime:
    return datetime(day.year, day.month, day.day, tzinfo=cfg.KST) + timedelta(seconds=sec)


StationTable = Callable[[str], "dict[int, ScheduledStop] | None"]


def live_delay_sec(t: TrainPosition, gasan_tt: dict[int, ScheduledStop], station_tt: StationTable,
                   day: date) -> int | None:
    """실시간 위치 수신 시각 - 그 역의 시간표 시각 (둘 다 API 값). 시간표에서 열차를 못 찾으면 None."""
    num = train_number(t.train_no)
    if num is None or t.generated_at is None:
        return None
    table = gasan_tt if t.stations_away == 0 else station_tt(t.station_name)
    stop = table.get(num) if table else None
    if stop is None:
        return None
    if t.status_code == "2":                     # 출발 → 출발시각과 비교
        ref = stop.leave_sec or stop.arrive_sec
    else:                                        # 진입·도착·전역출발·운행중 → 도착시각과 비교
        ref = stop.arrive_sec or stop.leave_sec
    if ref is None:
        return None
    delay = int((t.generated_at - at_day_sec(day, ref)).total_seconds())
    return delay if abs(delay) <= 3 * 3600 else None   # 엉뚱한 열차와 매칭된 경우 방지


def build_gasan_board(gasan_tt: dict[int, ScheduledStop] | None, live_trains: list[TrainPosition],
                      passed_nums: set[int], station_tt: StationTable, now: datetime) -> list[GasanTrain]:
    """시간표(가산 도착시각)를 기준으로, 실시간 위치가 있는 열차는 지연을 반영해 예상 도착을 만든다.

    - 시간표 + 실시간 위치 : 예상 = 시간표 + 지연 (일찍 와 있는 경우는 시간표대로)
    - 시간표만 (출발 전 / 위치 API 누락) : 예상 = 시간표. 시간표 시각이 SUBWAY_UNSEEN_GRACE_SEC 넘게 지나면 숨김
    - 실시간 위치만 (시간표에 없는 열차) : 시각 없이 위치만
    - 이미 가산을 지난 열차(passed_nums) 는 숨김
    """
    day = service_day(now)
    horizon = now + timedelta(minutes=cfg.SUBWAY_LOOKAHEAD_MIN)
    live_by_num: dict[int, TrainPosition] = {}
    for t in live_trains:
        n = train_number(t.train_no)
        if n is not None:
            live_by_num[n] = t
    board: list[GasanTrain] = []

    for num, stop in (gasan_tt or {}).items():
        ref = stop.arrive_sec or stop.leave_sec
        if ref is None or num in passed_nums:
            continue
        if normalize_station_name(stop.destination) in cfg.EXCLUDED_DESTINATIONS:
            continue
        scheduled = at_day_sec(day, ref)
        live = live_by_num.get(num)
        if live is not None:
            delay = live_delay_sec(live, gasan_tt, station_tt, day)
            if live.stations_away and now > scheduled:
                # 아직 가산에 안 왔는데 시간표 시각이 지났으면, 최소한 그만큼은 늦은 것
                delay = max(delay or 0, int((now - scheduled).total_seconds()))
            expected = scheduled + timedelta(seconds=max(0, delay or 0))
        else:
            if scheduled < now - timedelta(seconds=cfg.SUBWAY_UNSEEN_GRACE_SEC):
                continue
            delay, expected = None, scheduled
        if expected > horizon:
            continue
        board.append(GasanTrain(stop.train_no, stop.destination, stop.is_express, scheduled, expected, delay, live))

    for num, t in live_by_num.items():          # 시간표에 없는 실시간 열차
        if gasan_tt and num in gasan_tt:
            continue
        board.append(GasanTrain(t.train_no, t.destination, t.is_express, None, None, None, t))

    for g in board:
        g.at_station = g.live is not None and g.live.stations_away == 0 and g.live.status_code in ("0", "1")
        if g.at_station:
            g.remaining_sec = 0
        elif g.expected is not None:
            g.remaining_sec = max(0, int((g.expected - now).total_seconds()))
    far = datetime.max.replace(tzinfo=cfg.KST)
    board.sort(key=lambda g: (0 if g.at_station else 1, g.expected or far,
                              g.stations_away if g.stations_away is not None else 999))
    return board[: cfg.SUBWAY_MAX_ROWS]


class TimetableCache:
    """시간표는 운행일마다 한 번만 받는다 (가산 + 지연 계산에 필요한 역만, 필요할 때)."""

    RETRY_SEC = 300

    def __init__(self, api_key: str):
        self.api_key = api_key
        self._day: date | None = None
        self._stations: dict[str, str] | None = None
        self._tables: dict[str, dict[int, ScheduledStop]] = {}
        self._failed: dict[str, float] = {}

    def _roll(self, now: datetime) -> date:
        day = service_day(now)
        if day != self._day:
            self._day, self._stations, self._tables, self._failed = day, None, {}, {}
        return day

    def _load(self, station_cd: str, day: date) -> dict[int, ScheduledStop]:
        table = self._tables.get(station_cd)
        if table is None:
            data = timetable_api.fetch_timetable(self.api_key, station_cd, week_tag(day), cfg.SUBWAY_TIMETABLE_INOUT)
            table = self._tables[station_cd] = timetable_api.parse_timetable(data)
            log.info("timetable: station %s loaded (%d trains, week_tag %s)", station_cd, len(table), week_tag(day))
        return table

    def gasan(self, now: datetime) -> dict[int, ScheduledStop]:
        """가산 하행 시간표. 실패하면 ApiError."""
        return self._load(cfg.SUBWAY_TIMETABLE_STATION_CD, self._roll(now))

    def station(self, name: str, now: datetime) -> dict[int, ScheduledStop] | None:
        """실시간 위치 역의 하행 시간표 (지연 계산용). 실패해도 None 만 돌려준다."""
        day = self._roll(now)
        key = normalize_station_name(name)
        if time.monotonic() - self._failed.get(key, -1e9) < self.RETRY_SEC:
            return None
        try:
            if self._stations is None:
                self._stations = timetable_api.parse_line_stations(timetable_api.fetch_line_stations(self.api_key))
            code = self._stations.get(key)
            return self._load(code, day) if code else None
        except ApiError as e:
            log.warning("timetable: %s (%s) - %s", name, e.kind.value, e.message)
        except Exception:
            log.exception("timetable: %s unexpected error", name)
        self._failed[key] = time.monotonic()
        return None


# ---------------------------------------------------------------------------
# 서비스
# ---------------------------------------------------------------------------
class TransitService:
    def __init__(self, settings: Settings):
        self.settings = settings
        self.timetable = TimetableCache(settings.subway_api_key)

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
        now = now_kst()
        warnings: list[str] = []
        try:
            gasan_tt = self.timetable.gasan(now)
        except ApiError as e:
            log.warning("timetable gasan: %s (%s)", e.message, e.kind.value)
            gasan_tt = None
            warnings.append(f"⚠ 시간표를 불러오지 못해 도착 시각 없이 실시간 위치만 표시합니다. ({e.message})")
        live = select_approaching_trains(trains, now)
        live_nums = {train_number(t.train_no) for t in live}
        # 하행인데 가산 접근 구간에 없는 열차 = 이미 가산을 지난 열차 → 시간표에서도 숨김
        passed = {n for t in trains
                  if t.subway_id == cfg.SUBWAY_LINE_ID and t.updn_line == cfg.SUBWAY_SOUTHBOUND_UPDN
                  and (n := train_number(t.train_no)) is not None and n not in live_nums}
        board = build_gasan_board(gasan_tt, live, passed, lambda name: self.timetable.station(name, now), now)
        if not board:
            warnings.append(f"앞으로 {cfg.SUBWAY_LOOKAHEAD_MIN}분 안에 가산디지털단지역으로 오는 "
                            "독산 방면 1호선 열차가 없습니다.")
        return SubwayInfo(cfg.SUBWAY_STATION_NAME, cfg.SUBWAY_DIRECTION_LABEL, board, warnings=warnings)

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
