"""서울시 지하철 실시간 열차 위치정보 (realtimePosition).

realtimeStationArrival(역 도착정보) 대신 이 API 를 쓰는 이유 (2026-11-20 실측):
  - 도착정보 API 는 방향별로 가장 가까운 2~3대만 주고, 1호선은 위치 갱신이 수십 초~수 분 늦다.
    (예: 0435 서동탄행 가산 도착이 위치 API 에는 10:30:24, 도착정보 API 에는 약 40초 뒤 반영)
  - 1호선은 도착정보 API 의 barvlDt(도착 예정 초)가 항상 0 이라 쓸 수 있는 정보가 위치뿐이다.
  - 위치 API 는 노선 전체 열차 + 출발(trainSttus=2) 이벤트까지 준다.

호출: GET http://swopenAPI.seoul.go.kr/api/subway/{KEY}/json/realtimePosition/0/300/1호선
응답 (검증):
  정상: {"errorMessage": {"code": "INFO-000", ...},
         "realtimePositionList": [{"subwayId", "statnId", "statnNm", "trainNo", "updnLine",
                                   "statnTid", "statnTnm", "trainSttus", "directAt",
                                   "lstcarAt", "recptnDt", "lastRecptnDt", ...}]}
  오류: {"status": 500, "code": "INFO-100", "message": "..."}
"""
from __future__ import annotations

import logging
from datetime import datetime
from typing import Any
from urllib.parse import quote

from api import http_client
from api.errors import ApiError, ErrorKind
from config import settings as cfg
from models.subway import TrainPosition

log = logging.getLogger(__name__)
LABEL = "subway"


def fetch_subway_raw(api_key: str) -> dict[str, Any]:
    if not api_key:
        raise ApiError(ErrorKind.NO_KEY, "지하철 API KEY가 없습니다. .env 파일의 SEOUL_SUBWAY_API_KEY를 확인해 주세요.")
    url = cfg.SUBWAY_API_URL.format(
        key=quote(api_key, safe=""),
        end=cfg.SUBWAY_QUERY_END,
        line=quote(cfg.SUBWAY_QUERY_LINE, safe=""),
    )
    resp = http_client.get(url, label=LABEL)
    return http_client.parse_json(resp, label=LABEL)


def parse_subway_response(data: Any) -> list[TrainPosition]:
    """응답 전체를 TrainPosition 목록으로 변환 (필터링 전). 같은 열차가 중복되면 최신 것만 남긴다."""
    if not isinstance(data, dict):
        raise ApiError(ErrorKind.PARSE, "지하철 API 응답 형식이 올바르지 않습니다.")

    status = data.get("errorMessage") or data  # 오류 시 최상위에 code/message 가 옴
    code = str(status.get("code") or "").strip()
    message = str(status.get("message") or "").strip()

    if code == "INFO-200":  # 해당하는 데이터 없음
        return []
    if code == "INFO-100":
        raise ApiError(ErrorKind.AUTH, "지하철 API 인증키가 유효하지 않습니다. SEOUL_SUBWAY_API_KEY를 확인해 주세요.")
    if code in ("ERROR-336", "ERROR-337"):
        raise ApiError(ErrorKind.LIMIT, "지하철 API 호출 한도를 초과했습니다. 잠시 후(또는 내일) 다시 조회해 주세요.")
    if code and code != "INFO-000":
        raise ApiError(ErrorKind.SERVER, f"지하철 API 오류: {message or '알 수 없는 오류'} ({code})")

    rows = data.get("realtimePositionList")
    if rows is None:
        if not code:
            raise ApiError(ErrorKind.PARSE, "지하철 API 응답에 열차 위치 항목이 없습니다.")
        return []
    if not isinstance(rows, list):
        raise ApiError(ErrorKind.PARSE, "지하철 API 응답 형식이 올바르지 않습니다.")

    latest: dict[str, TrainPosition] = {}
    anonymous: list[TrainPosition] = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        try:
            t = _parse_row(row)
        except Exception:  # 한 행의 이상 데이터로 전체가 실패하지 않도록
            log.warning("subway: skip malformed row", exc_info=True)
            continue
        if not t.train_no:
            anonymous.append(t)
            continue
        prev = latest.get(t.train_no)
        if prev is None or _ts(t) >= _ts(prev):
            latest[t.train_no] = t
    return list(latest.values()) + anonymous


def _ts(t: TrainPosition) -> float:
    return t.generated_at.timestamp() if t.generated_at else 0.0


def _parse_row(row: dict[str, Any]) -> TrainPosition:
    def s(key: str) -> str:
        v = row.get(key)
        return "" if v is None else str(v).strip()

    return TrainPosition(
        train_no=s("trainNo"),
        subway_id=s("subwayId"),
        updn_line=s("updnLine"),
        station_id=s("statnId"),
        station_name=s("statnNm"),
        destination=s("statnTnm"),
        status_code=s("trainSttus"),
        is_express=s("directAt") == "1",
        is_last=s("lstcarAt") == "1",
        generated_at=_parse_time(s("recptnDt")),
    )


def _parse_time(value: str) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.strptime(value.split(".")[0], "%Y-%m-%d %H:%M:%S").replace(tzinfo=cfg.KST)
    except ValueError:
        return None
