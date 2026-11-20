"""버스 파싱/HTTP 오류 테스트. fixture 는 2026-11-20 10:03:07 실제 getArrInfoByRoute 응답."""
import copy
from datetime import datetime

import pytest
import requests

from api import bus_api, http_client, subway_api
from api.bus_api import parse_bus_response
from api.errors import ApiError, ErrorKind
from config import settings as cfg
from config.settings import Settings
from models.bus import BusStatus
from services.transit_service import TransitService

NOW = datetime(2026, 11, 20, 10, 3, 17, tzinfo=cfg.KST)  # mkTm + 10초
SECRET = "6ff3771c-test-secret"


def test_real_fixture(load_fixture):
    info = parse_bus_response(load_fixture("bus_17635_20261120.json"), NOW)
    assert info.route_name == "금천07"
    assert info.station_name == "JNK디지털타워"
    assert info.ars_id == "17635"
    assert not info.warnings and not info.stale
    first, second = info.arrivals
    assert first.status == BusStatus.RUNNING
    assert first.remaining_sec == 273 - 10        # traTime1 - 경과시간
    assert first.stops_away == 1
    assert first.current_stop == "구로디지털단지입구"
    assert second.remaining_sec == 677 - 10
    assert second.stops_away == 5


def _item(load_fixture, **over):
    data = load_fixture("bus_17635_20261120.json")
    data["msgBody"]["itemList"][0].update(over)
    return data


def test_waiting_and_ended(load_fixture):
    info = parse_bus_response(_item(load_fixture, arrmsg1="출발대기", traTime1="0",
                                    arrmsg2="운행종료", traTime2="0"), NOW)
    assert info.arrivals[0].status == BusStatus.WAITING
    assert info.arrivals[1].status == BusStatus.ENDED
    assert info.arrivals[0].remaining_sec is None


def test_arriving_soon(load_fixture):
    info = parse_bus_response(_item(load_fixture, arrmsg1="곧 도착", traTime1="0"), NOW)
    assert info.arrivals[0].status == BusStatus.ARRIVING_SOON


def test_station_mismatch_raises(load_fixture):
    with pytest.raises(ApiError) as ei:
        parse_bus_response(_item(load_fixture, stId="999"), NOW)
    assert ei.value.kind == ErrorKind.NO_DATA


def test_route_order_change_warns(load_fixture):
    info = parse_bus_response(_item(load_fixture, staOrd="30"), NOW)
    assert info.warnings


def test_stale(load_fixture):
    info = parse_bus_response(_item(load_fixture, mkTm="2026-11-20 09:50:00.0"), NOW)
    assert info.stale


def test_no_result_header():
    info = parse_bus_response({"msgHeader": {"headerCd": "4", "headerMsg": "결과없음"}, "msgBody": {}}, NOW)
    assert info.arrivals == []


@pytest.mark.parametrize("cd,kind", [("7", ErrorKind.AUTH), ("8", ErrorKind.LIMIT), ("1", ErrorKind.SERVER)])
def test_header_errors(cd, kind):
    with pytest.raises(ApiError) as ei:
        parse_bus_response({"msgHeader": {"headerCd": cd, "headerMsg": "err"}}, NOW)
    assert ei.value.kind == kind


def test_gateway_unauthorized_body():
    with pytest.raises(ApiError) as ei:
        parse_bus_response({"error": "Unauthorized", "message": "등록되지 않은 서비스키", "status": 401}, NOW)
    assert ei.value.kind == ErrorKind.AUTH


# ---------------------------------------------------------------------------
# HTTP 계층: 한국어 메시지 + 인증키 비노출
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("exc,kind", [
    (requests.exceptions.ConnectionError("http://x?serviceKey=" + SECRET), ErrorKind.NETWORK),
    (requests.exceptions.ReadTimeout("http://x?serviceKey=" + SECRET), ErrorKind.TIMEOUT),
    (requests.exceptions.ConnectTimeout("http://x?serviceKey=" + SECRET), ErrorKind.TIMEOUT),
])
def test_network_errors_hide_key(monkeypatch, exc, kind):
    def boom(*a, **k):
        raise exc
    monkeypatch.setattr(requests, "get", boom)
    with pytest.raises(ApiError) as ei:
        bus_api.fetch_bus_raw(SECRET)
    assert ei.value.kind == kind
    assert SECRET not in ei.value.message
    assert ei.value.__cause__ is None and ei.value.__suppress_context__


class _Resp:
    def __init__(self, status, text):
        self.status_code, self.text = status, text

    def json(self):
        import json
        return json.loads(self.text)


@pytest.mark.parametrize("status,kind", [(401, ErrorKind.AUTH), (429, ErrorKind.LIMIT), (503, ErrorKind.SERVER)])
def test_http_status(monkeypatch, status, kind):
    monkeypatch.setattr(requests, "get", lambda *a, **k: _Resp(status, "{}"))
    with pytest.raises(ApiError) as ei:
        bus_api.fetch_bus_raw(SECRET)
    assert ei.value.kind == kind


def test_xml_key_error(monkeypatch):
    xml = "<OpenAPI_ServiceResponse><returnAuthMsg>SERVICE_KEY_IS_NOT_REGISTERED_ERROR</returnAuthMsg></OpenAPI_ServiceResponse>"
    monkeypatch.setattr(requests, "get", lambda *a, **k: _Resp(200, xml))
    with pytest.raises(ApiError) as ei:
        bus_api.fetch_bus_raw(SECRET)
    assert ei.value.kind == ErrorKind.AUTH


def test_invalid_json(monkeypatch):
    monkeypatch.setattr(requests, "get", lambda *a, **k: _Resp(200, "not json"))
    with pytest.raises(ApiError) as ei:
        subway_api.fetch_subway_raw(SECRET)
    assert ei.value.kind == ErrorKind.PARSE


def test_missing_key():
    with pytest.raises(ApiError) as ei:
        bus_api.fetch_bus_raw("")
    assert ei.value.kind == ErrorKind.NO_KEY


def test_one_side_failure_does_not_block_other(monkeypatch, load_fixture):
    """버스 API 가 실패해도 지하철 결과는 정상 반환."""
    monkeypatch.setattr(bus_api, "fetch_bus_raw", lambda key: (_ for _ in ()).throw(
        ApiError(ErrorKind.NETWORK, "서버에 연결할 수 없습니다.")))
    monkeypatch.setattr(subway_api, "fetch_subway_raw", lambda key: load_fixture("position_line1_20261120.json"))
    svc = TransitService(Settings("k1", "k2", False, None))
    r = svc.query()
    assert r.bus is None and "연결" in r.bus_error
    assert r.subway is not None and r.subway_error is None


def test_mock_mode_marks_data():
    r = TransitService(Settings("", "", True, None)).query()
    assert r.is_mock and r.bus.is_mock and r.subway.is_mock
    assert len(r.bus.arrivals) == 2
    kinds = [a.train_type for a in r.subway.arrivals]
    assert kinds.count("일반") == 3 and kinds.count("급행") == 2
