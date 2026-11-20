"""서울시 지하철 역별 열차 시간표 (서울 열린데이터광장 일반 Open API, 실시간 지하철과 같은 키).

1호선(코레일 구간)은 실시간 API 에 도착 예정시간(barvlDt)이 없어서(항상 0, 2026-11-20 확인),
'언제 오는지' 는 이 시간표 API 값을 기준으로 한다.

  역 목록: GET http://openAPI.seoul.go.kr:8088/{KEY}/json/SearchSTNBySubwayLineInfo/1/1000/ / /01호선
           → row: STATION_CD, STATION_NM, FR_CODE ...
  시간표 : GET http://openAPI.seoul.go.kr:8088/{KEY}/json/SearchSTNTimeTableByIDService/1/1000/{STATION_CD}/{WEEK_TAG}/{INOUT_TAG}/
           WEEK_TAG 1 평일 / 2 토요일 / 3 휴일·일요일, INOUT_TAG 1 상행 / 2 하행
           → row: TRAIN_NO("K645"), ARRIVETIME("11:54:00"), LEFTTIME, SUBWAYSNAME(출발역), SUBWAYENAME(행선지),
                  EXPRESS_YN(D 급행 / G 일반) ...
  오류   : {"RESULT": {"CODE": "INFO-100", "MESSAGE": "..."}} (서비스 키 아래 또는 최상위)
"""
from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from typing import Any
from urllib.parse import quote

from api import http_client
from api.errors import ApiError, ErrorKind
from config import settings as cfg
from models.subway import normalize_station_name

log = logging.getLogger(__name__)
LABEL = "timetable"
_SVC_STATIONS = "SearchSTNBySubwayLineInfo"
_SVC_TIMETABLE = "SearchSTNTimeTableByIDService"
_DIGITS = re.compile(r"\d+")


@dataclass(frozen=True)
class ScheduledStop:
    """한 역에서의 열차 1편 시간표. 시각은 운행일 0시 기준 초 (자정 넘으면 24시간 이상)."""
    train_num: int        # 열차번호 숫자 (실시간 0645 ↔ 시간표 K645 를 같은 번호로 맞춤)
    train_no: str         # 시간표 원문 (K645)
    arrive_sec: int | None
    leave_sec: int | None
    origin: str
    destination: str
    is_express: bool


def train_number(value: str) -> int | None:
    """'0645', 'K645', 'S445' → 645, 445. 숫자가 없으면 None."""
    m = _DIGITS.search(value or "")
    return int(m.group()) if m else None


def _url(api_key: str, service: str, *args: str) -> str:
    path = "/".join(quote(a, safe="") for a in args)
    return cfg.SUBWAY_OPENAPI_URL.format(key=quote(api_key, safe=""), service=service, args=path)


def _rows(data: Any, service: str) -> list[dict]:
    if not isinstance(data, dict):
        raise ApiError(ErrorKind.PARSE, "시간표 API 응답 형식이 올바르지 않습니다.")
    body = data.get(service) if isinstance(data.get(service), dict) else data
    result = body.get("RESULT") or {}
    code = str(result.get("CODE") or "").strip()
    if code == "INFO-200":
        return []
    if code == "INFO-100":
        raise ApiError(ErrorKind.AUTH, "시간표 API 인증키가 유효하지 않습니다. SEOUL_SUBWAY_API_KEY를 확인해 주세요.")
    if code in ("ERROR-336", "ERROR-337"):
        raise ApiError(ErrorKind.LIMIT, "시간표 API 호출 한도를 초과했습니다.")
    if code and code != "INFO-000":
        raise ApiError(ErrorKind.SERVER, f"시간표 API 오류: {result.get('MESSAGE') or '알 수 없는 오류'} ({code})")
    rows = body.get("row")
    return [r for r in rows if isinstance(r, dict)] if isinstance(rows, list) else []


def fetch_line_stations(api_key: str) -> dict:
    url = _url(api_key, _SVC_STATIONS, "1", "1000", " ", " ", cfg.SUBWAY_TIMETABLE_LINE)
    return http_client.parse_json(http_client.get(url, label=LABEL), label=LABEL)


def parse_line_stations(data: Any) -> dict[str, str]:
    """역 이름(정규화) → STATION_CD."""
    out: dict[str, str] = {}
    for r in _rows(data, _SVC_STATIONS):
        name, code = str(r.get("STATION_NM") or "").strip(), str(r.get("STATION_CD") or "").strip()
        if name and code:
            out[normalize_station_name(name)] = code
    return out


def fetch_timetable(api_key: str, station_cd: str, week_tag: str, inout_tag: str) -> dict:
    url = _url(api_key, _SVC_TIMETABLE, "1", "1000", station_cd, week_tag, inout_tag) + "/"
    return http_client.parse_json(http_client.get(url, label=LABEL), label=LABEL)


def parse_timetable(data: Any) -> dict[int, ScheduledStop]:
    """열차번호(숫자) → 그 역 시간표."""
    out: dict[int, ScheduledStop] = {}
    for r in _rows(data, _SVC_TIMETABLE):
        def s(key: str) -> str:
            v = r.get(key)
            return "" if v is None else str(v).strip()
        num = train_number(s("TRAIN_NO"))
        if num is None:
            continue
        out[num] = ScheduledStop(
            train_num=num, train_no=s("TRAIN_NO"),
            arrive_sec=_clock_sec(s("ARRIVETIME")), leave_sec=_clock_sec(s("LEFTTIME")),
            origin=s("SUBWAYSNAME"), destination=s("SUBWAYENAME"), is_express=s("EXPRESS_YN") == "D",
        )
    return out


def _clock_sec(value: str) -> int | None:
    """'HH:MM:SS' → 운행일 기준 초. 새벽(운행일 시작 시각 이전)은 다음날로 본다. '00:00:00' 은 값 없음 취급."""
    parts = value.split(":")
    if len(parts) < 2 or not all(p.isdigit() for p in parts):
        return None
    h, m = int(parts[0]), int(parts[1])
    sec = int(parts[2]) if len(parts) > 2 else 0
    total = h * 3600 + m * 60 + sec
    if total == 0:
        return None
    if h < cfg.SERVICE_DAY_START_HOUR:
        total += 24 * 3600
    return total
