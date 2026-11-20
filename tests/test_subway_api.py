"""지하철(realtimePosition) 파싱/필터 테스트. fixture 는 2026-11-20 10:31:45 실제 1호선 위치 응답."""
from datetime import datetime

import pytest

from api.errors import ApiError, ErrorKind
from api.subway_api import parse_subway_response
from config import settings as cfg
from services.transit_service import select_approaching_trains, stations_until_gasan

NOW = datetime(2026, 11, 20, 10, 32, 0, tzinfo=cfg.KST)
GASAN = cfg.SUBWAY_STATION_ID


def _row(**over):
    base = {
        "subwayId": "1001", "statnId": "1001000136", "statnNm": "노량진", "trainNo": "0637",
        "updnLine": "1", "statnTid": "1001080169", "statnTnm": "천안", "trainSttus": "1",
        "directAt": "0", "lstcarAt": "0", "recptnDt": "2026-11-20 10:31:30",
    }
    base.update(over)
    return base


def _data(*rows):
    return {"errorMessage": {"status": 200, "code": "INFO-000", "message": "정상"},
            "realtimePositionList": list(rows)}


def _select(*rows):
    return select_approaching_trains(parse_subway_response(_data(*rows)), NOW)


def test_real_fixture(load_fixture):
    trains = parse_subway_response(load_fixture("position_line1_20261120.json"))
    selected = select_approaching_trains(trains, NOW)
    got = [(t.train_no, t.destination, t.stations_away, t.train_type) for t in selected]
    # 구로행·인천행·광운대행(가산 미경유), 서동탄·광명행(개인 제외), 상행, 경인선 위 열차는 제외
    assert got == [
        ("0635", "신창", 1, "일반"),    # 구로
        ("0637", "천안", 6, "일반"),    # 노량진
        ("0639", "신창", 8, "일반"),    # 남영
        ("1915", "천안", 18, "급행"),   # 청량리
        ("0641", "신창", 19, "일반"),   # 회기
    ]


def test_duplicate_train_rows_keep_latest():
    trains = parse_subway_response(_data(
        _row(statnId="1001000135", statnNm="용산", recptnDt="2026-11-20 10:29:00"),
        _row(statnId="1001000136", statnNm="노량진", recptnDt="2026-11-20 10:31:00"),
    ))
    assert len(trains) == 1 and trains[0].station_name == "노량진"


def test_stations_until_gasan():
    assert stations_until_gasan(GASAN) == 0
    assert stations_until_gasan("1001000141") == 1    # 구로
    assert stations_until_gasan("1001000124") == 18   # 청량리
    assert stations_until_gasan("1001000152") is None  # 부평 (경인선)
    assert stations_until_gasan("1001080144") is None  # 금천구청 (이미 지나감)
    assert stations_until_gasan("1007000746") is None  # 7호선


def test_not_decided_by_updn_alone():
    # 하행이지만 경인선 위(부평) → 가산으로 오지 않음
    assert _select(_row(statnId="1001000152", statnNm="부평")) == []
    # 상행 열차 제외
    assert _select(_row(updnLine="0")) == []


def test_destinations_that_never_reach_gasan_excluded():
    for dest in ("구로", "인천", "동인천", "광운대", "영등포"):
        assert _select(_row(statnTnm=dest)) == [], dest


def test_personal_excluded_destinations():
    for dest in ("광명", "서동탄", "병점", "수원"):
        assert _select(_row(statnTnm=dest)) == [], dest


def test_destination_name_with_parentheses():
    assert len(_select(_row(statnTnm="쌍용(나사렛대)"))) == 1


def test_express_included():
    selected = _select(_row(directAt="1"))
    assert selected[0].train_type == "급행"


def test_departed_or_old_at_gasan_hidden():
    at = dict(statnId=GASAN, statnNm="가산디지털단지")
    assert _select(_row(**at, trainSttus="2", recptnDt="2026-11-20 10:31:50")) == []   # 출발
    assert _select(_row(**at, trainSttus="1", recptnDt="2026-11-20 10:28:00")) == []   # 4분 전 도착
    fresh = _select(_row(**at, trainSttus="0", recptnDt="2026-11-20 10:31:40"))
    assert len(fresh) == 1 and fresh[0].stations_away == 0


def test_age_and_stale():
    t = _select(_row(recptnDt="2026-11-20 10:30:00"))[0]
    assert t.age_sec == 120 and not t.stale
    t = _select(_row(recptnDt="2026-11-20 10:25:00"))[0]
    assert t.stale


def test_sorted_by_stations():
    selected = _select(
        _row(trainNo="a", statnId="1001000124", statnNm="청량리"),
        _row(trainNo="b", statnId="1001000141", statnNm="구로"),
        _row(trainNo="c", statnId="1001000139", statnNm="영등포"),
    )
    assert [t.train_no for t in selected] == ["b", "c", "a"]


def test_no_data_code_returns_empty():
    assert parse_subway_response({"status": 200, "code": "INFO-200", "message": "없음"}) == []


@pytest.mark.parametrize("code,kind", [("INFO-100", ErrorKind.AUTH), ("ERROR-337", ErrorKind.LIMIT),
                                       ("ERROR-500", ErrorKind.SERVER)])
def test_error_codes(code, kind):
    with pytest.raises(ApiError) as ei:
        parse_subway_response({"status": 500, "code": code, "message": "x"})
    assert ei.value.kind == kind


def test_malformed_response():
    with pytest.raises(ApiError) as ei:
        parse_subway_response({"foo": "bar"})
    assert ei.value.kind == ErrorKind.PARSE


def test_missing_fields_do_not_crash():
    trains = parse_subway_response(_data({"subwayId": "1001"}))
    assert len(trains) == 1
    assert select_approaching_trains(trains, NOW) == []
