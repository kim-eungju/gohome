"""서울특별시_버스도착정보조회 서비스 - getArrInfoByRoute (특정 노선의 특정 정류소 도착정보).

검증된 응답 구조 (resultType=json):
    {"msgHeader": {"headerCd": "0", "headerMsg": "...", "itemCount": 0},
     "msgBody": {"itemList": [{ "stId", "arsId", "stNm", "busRouteId", "rtNm", "staOrd",
                                "arrmsg1", "traTime1", "sectOrd1", "stationNm1", "plainNo1",
                                "isLast1", "mkTm", ... (2번째 버스는 *2) }]}}
인증 실패 시(공공데이터포털 게이트웨이): HTTP 401 {"error": "Unauthorized", "message": ...}
"""
from __future__ import annotations

import logging
import re
from datetime import datetime
from typing import Any
from urllib.parse import unquote

from api import http_client
from api.errors import ApiError, ErrorKind
from config import settings as cfg
from models.bus import BusArrival, BusInfo, BusStatus

log = logging.getLogger(__name__)
LABEL = "bus"

_TIME_RE = re.compile(r"(?:(\d+)\s*분)?\s*(?:(\d+)\s*초)?\s*후")
_STOPS_RE = re.compile(r"\[(\d+)\s*번째\s*전\]")


def fetch_bus_raw(api_key: str) -> dict[str, Any]:
    if not api_key:
        raise ApiError(ErrorKind.NO_KEY, "버스 API KEY가 없습니다. .env 파일의 SEOUL_BUS_API_KEY를 확인해 주세요.")
    params = {
        # Encoding 키(%2B 등 포함)를 넣어도 이중 인코딩되지 않도록 디코딩 후 전달
        "serviceKey": unquote(api_key),
        "stId": cfg.BUS_STATION_ID,
        "busRouteId": cfg.BUS_ROUTE_ID,
        "ord": cfg.BUS_STATION_ORD,
        "resultType": "json",
    }
    resp = http_client.get(cfg.BUS_API_URL, params, label=LABEL)
    text = resp.text.lstrip()
    if text.startswith("<"):
        _raise_from_xml(text)
    return http_client.parse_json(resp, label=LABEL)


def _raise_from_xml(text: str) -> None:
    """공공데이터포털이 XML 형식 오류를 돌려주는 경우 처리."""
    upper = text.upper()
    if "SERVICE_KEY" in upper or "SERVICEKEY" in upper or "인증" in text:
        raise ApiError(ErrorKind.AUTH, "버스 API 인증에 실패했습니다. API KEY와 활용신청 승인 상태를 확인해 주세요.")
    if "LIMITED" in upper or "EXCEED" in upper:
        raise ApiError(ErrorKind.LIMIT, "버스 API 호출 한도를 초과했습니다. 잠시 후 다시 조회해 주세요.")
    log.warning("bus: unexpected XML response %r", text[:120])
    raise ApiError(ErrorKind.PARSE, "버스 API 응답 형식을 해석할 수 없습니다.")


def parse_bus_response(data: Any, now: datetime) -> BusInfo:
    """API 응답(dict)을 BusInfo 로 변환. now 는 KST aware datetime."""
    if not isinstance(data, dict):
        raise ApiError(ErrorKind.PARSE, "버스 API 응답 형식이 올바르지 않습니다.")
    if "error" in data and "msgHeader" not in data:
        raise ApiError(ErrorKind.AUTH, "버스 API 인증에 실패했습니다. API KEY를 확인해 주세요.")

    header = data.get("msgHeader") or {}
    code = str(header.get("headerCd", "")).strip()
    msg = str(header.get("headerMsg") or "").strip()

    if code == "4":  # 결과 없음
        return _empty_info(["현재 금천07 도착 예정 정보가 없습니다."])
    if code in ("5", "6", "7"):
        raise ApiError(ErrorKind.AUTH, f"버스 API 인증에 실패했습니다. ({msg or 'API KEY 오류'})")
    if code == "8":
        raise ApiError(ErrorKind.LIMIT, "버스 API 호출 한도를 초과했습니다. 잠시 후 다시 조회해 주세요.")
    if code != "0":
        raise ApiError(ErrorKind.SERVER, f"버스 API 오류: {msg or '알 수 없는 오류'} (코드 {code or '없음'})")

    items = (data.get("msgBody") or {}).get("itemList") or []
    if isinstance(items, dict):  # 1건일 때 dict 로 오는 경우 대비
        items = [items]
    if not items:
        return _empty_info(["현재 금천07 도착 예정 정보가 없습니다."])

    item = next((it for it in items
                 if str(it.get("stId")) == cfg.BUS_STATION_ID
                 and str(it.get("busRouteId")) == cfg.BUS_ROUTE_ID), None)
    if item is None:
        raise ApiError(ErrorKind.NO_DATA, "응답에 금천07 / JNK디지털타워 정보가 없습니다. 정류장 설정을 확인해 주세요.")

    warnings: list[str] = []
    if str(item.get("arsId", "")).strip() != cfg.BUS_STATION_ARS_ID:
        warnings.append(f"정류장 번호가 설정값과 다릅니다 (API: {item.get('arsId')}).")
    if str(item.get("staOrd", "")).strip() != str(cfg.BUS_STATION_ORD):
        warnings.append("노선 순번이 바뀌었습니다. 노선 경로 변경 여부를 확인해 주세요.")

    generated_at = _parse_time(item.get("mkTm"))
    elapsed = _elapsed(generated_at, now)
    stale = generated_at is None or elapsed > cfg.STALE_AFTER_SEC
    if generated_at is None:
        warnings.append("데이터 생성 시각이 없어 남은 시간은 참고용입니다.")

    arrivals = [_parse_arrival(item, i, elapsed) for i in (1, 2)]
    return BusInfo(
        route_name=str(item.get("rtNm") or cfg.BUS_ROUTE_NAME),
        station_name=str(item.get("stNm") or cfg.BUS_STATION_NAME),
        ars_id=str(item.get("arsId") or cfg.BUS_STATION_ARS_ID),
        direction=cfg.BUS_DIRECTION_LABEL,
        arrivals=arrivals,
        generated_at=generated_at,
        stale=stale,
        warnings=warnings,
    )


def _empty_info(warnings: list[str]) -> BusInfo:
    return BusInfo(cfg.BUS_ROUTE_NAME, cfg.BUS_STATION_NAME, cfg.BUS_STATION_ARS_ID,
                   cfg.BUS_DIRECTION_LABEL, [], None, warnings=warnings)


def _parse_arrival(item: dict[str, Any], idx: int, elapsed: int) -> BusArrival:
    msg = str(item.get(f"arrmsg{idx}") or "").strip()
    tra = _to_int(item.get(f"traTime{idx}"))
    plate = str(item.get(f"plainNo{idx}") or "").strip() or None
    current = str(item.get(f"stationNm{idx}") or "").strip() or None
    is_last = str(item.get(f"isLast{idx}") or "0").strip() == "1"

    stops = None
    m = _STOPS_RE.search(msg)
    if m:
        stops = int(m.group(1))
    else:
        sect = _to_int(item.get(f"sectOrd{idx}"))
        sta = _to_int(item.get("staOrd"))
        if sect and sta and sta >= sect:
            stops = sta - sect

    def make(status: BusStatus, remaining: int | None = None) -> BusArrival:
        return BusArrival(idx, status, remaining, stops, current, plate, is_last, msg)

    if not msg and not tra:
        return BusArrival(idx, BusStatus.NO_INFO, None, None, None, None, False, "")
    if "운행종료" in msg:
        return BusArrival(idx, BusStatus.ENDED, None, None, None, None, False, msg)
    if "출발대기" in msg:
        return BusArrival(idx, BusStatus.WAITING, None, None, None, None, is_last, msg)
    if "곧 도착" in msg:
        return make(BusStatus.ARRIVING_SOON, 0)

    sec = tra if tra and tra > 0 else _parse_msg_seconds(msg)
    if sec is None:
        return make(BusStatus.NO_INFO)
    return make(BusStatus.RUNNING, max(0, sec - elapsed))


def _parse_msg_seconds(msg: str) -> int | None:
    m = _TIME_RE.search(msg)
    if not m or (m.group(1) is None and m.group(2) is None):
        return None
    return int(m.group(1) or 0) * 60 + int(m.group(2) or 0)


def _parse_time(value: Any) -> datetime | None:
    s = str(value or "").strip()
    if not s:
        return None
    s = s.split(".")[0]
    try:
        return datetime.strptime(s, "%Y-%m-%d %H:%M:%S").replace(tzinfo=cfg.KST)
    except ValueError:
        return None


def _elapsed(generated_at: datetime | None, now: datetime) -> int:
    if generated_at is None:
        return 0
    return max(0, int((now - generated_at).total_seconds()))


def _to_int(value: Any) -> int | None:
    try:
        return int(str(value).strip())
    except (TypeError, ValueError):
        return None
