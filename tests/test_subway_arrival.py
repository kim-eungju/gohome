"""위치 API 에 빠진 열차를 역 도착정보 API 로 보충하는 테스트.

fixture: 2026-11-20 11:56:22 가산디지털단지 realtimeStationArrival 실제 응답.
같은 시각 realtimePosition 에는 구로 도착 중인 0645 신창행이 없었다.
"""
from datetime import datetime

from api.subway_api import parse_arrival_response
from config import settings as cfg
from models.subway import TrainPosition
from services.transit_service import merge_missing_trains, select_approaching_trains

NOW = datetime(2026, 11, 20, 11, 56, 22, tzinfo=cfg.KST)


def _pos(train_no, station_id, dest, status="1"):
    return TrainPosition(train_no, "1001", "1", station_id, "", dest, status, False, False,
                         datetime(2026, 11, 20, 11, 55, 40, tzinfo=cfg.KST))


def test_parse_arrival_fixture(load_fixture):
    got = {t.train_no: (t.destination, t.station_name, t.stations_away, t.status_code)
           for t in parse_arrival_response(load_fixture("arrival_gasan_20261120.json"))}
    assert got == {
        "0445": ("서동탄", "가산디지털단지", 0, "1"),
        "1919": ("천안", "서울", 9, ""),
        "0645": ("신창", "구로", 1, "1"),      # 전역(구로) 도착
        "1921": ("천안", "청량리", 18, ""),
    }


def test_missing_train_is_filled_and_shown(load_fixture):
    positions = [_pos("1919", "1001000133", "천안"), _pos("1921", "1001000124", "천안")]
    arrivals = parse_arrival_response(load_fixture("arrival_gasan_20261120.json"))
    merged = merge_missing_trains(positions, arrivals)
    # 위치 API 에 이미 있는 1919·1921 은 중복으로 넣지 않는다
    assert sorted(t.train_no for t in merged) == ["0445", "0645", "1919", "1921"]

    selected = select_approaching_trains(merged, NOW)
    by_no = {t.train_no: t for t in selected}
    assert "0645" in by_no and by_no["0645"].from_arrival_api
    assert by_no["0645"].stations_away == 1
    assert "0445" not in by_no            # 서동탄행은 개인 제외 행선지


def test_arrival_parse_ignores_garbage():
    assert parse_arrival_response(None) == []
    assert parse_arrival_response({"status": 500, "code": "INFO-100"}) == []
    assert parse_arrival_response({"realtimeArrivalList": [{"subwayId": "1001", "updnLine": "하행"}]}) == []
