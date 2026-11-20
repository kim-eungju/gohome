"""시간표 API 파싱 + '시간표 + 실시간 지연' 으로 가산 도착 예정 만들기.

fixture: 2026-11-20 서울 열린데이터광장 실제 응답
  - timetable_gasan_down_weekday.json : SearchSTNTimeTableByIDService 1702(가산디지털단지)/평일/하행
  - line1_stations.json               : SearchSTNBySubwayLineInfo 01호선
"""
from datetime import date, datetime

import pytest

from api.errors import ApiError, ErrorKind
from api.timetable_api import ScheduledStop, parse_line_stations, parse_timetable, train_number
from config import settings as cfg
from models.subway import TrainPosition
from services.transit_service import build_gasan_board, service_day, week_tag

DAY = date(2026, 11, 20)


def _at(h, m, s=0):
    return datetime(2026, 11, 20, h, m, s, tzinfo=cfg.KST)


def _live(no, station, away, status="1", at=None):
    return TrainPosition(no, "1001", "1", "", station, "신창", status, False, False, at,
                         stations_away=away, age_sec=0)


def _stop(no, arrive, leave=None, dest="신창", express=False):
    def sec(t):
        h, m = t.split(":")
        return int(h) * 3600 + int(m) * 60
    return ScheduledStop(train_number(no), no, sec(arrive), sec(leave or arrive), "구로", dest, express)


def test_train_number_matches_realtime_and_timetable():
    assert train_number("0645") == train_number("K645") == 645
    assert train_number("S445") == 445
    assert train_number("K1919") == train_number("1919")
    assert train_number("") is None


def test_parse_real_timetable(load_fixture):
    tt = parse_timetable(load_fixture("timetable_gasan_down_weekday.json"))
    assert len(tt) == 154
    k647 = tt[647]
    assert (k647.train_no, k647.destination, k647.is_express) == ("K647", "신창", False)
    assert k647.arrive_sec == 12 * 3600 + 20 * 60
    assert tt[1919].is_express                           # EXPRESS_YN = D


def test_parse_line_stations(load_fixture):
    st = parse_line_stations(load_fixture("line1_stations.json"))
    assert st["가산디지털단지"] == "1702"
    assert st["구로"] == "1701"
    assert st["서울"] == "0150"                          # 실시간은 '서울', 목록은 '서울역'


def test_timetable_error_codes():
    with pytest.raises(ApiError) as ei:
        parse_timetable({"RESULT": {"CODE": "INFO-100", "MESSAGE": "x"}})
    assert ei.value.kind == ErrorKind.AUTH
    assert parse_timetable({"SearchSTNTimeTableByIDService": {"RESULT": {"CODE": "INFO-200"}}}) == {}


def test_service_day_and_week_tag():
    assert service_day(datetime(2026, 11, 21, 1, 0, tzinfo=cfg.KST)) == DAY   # 새벽 1시 = 전날 운행일
    assert week_tag(date(2026, 11, 20)) == "1"   # 금
    assert week_tag(date(2026, 11, 21)) == "2"   # 토
    assert week_tag(date(2026, 11, 22)) == "3"   # 일


def test_delay_from_live_position_is_added():
    gasan = {647: _stop("K647", "12:20")}
    guro = {647: _stop("K647", "12:16", "12:16")}
    live = [_live("0647", "구로", 1, "1", at=_at(12, 18))]              # 구로 도착이 2분 늦음
    board = build_gasan_board(gasan, live, set(), lambda name: guro if name == "구로" else None, _at(12, 19))
    g = board[0]
    assert g.scheduled == _at(12, 20) and g.delay_sec == 120
    assert g.expected == _at(12, 22) and g.remaining_sec == 180


def test_early_train_keeps_schedule():
    gasan = {647: _stop("K647", "12:20")}
    guro = {647: _stop("K647", "12:16")}
    live = [_live("0647", "구로", 1, at=_at(12, 14))]                  # 2분 일찍 와 있음
    g = build_gasan_board(gasan, live, set(), lambda n: guro, _at(12, 15))[0]
    assert g.delay_sec == -120 and g.expected == _at(12, 20)


def test_overdue_live_train_counts_as_late():
    gasan = {647: _stop("K647", "12:20")}
    guro = {647: _stop("K647", "12:16")}
    live = [_live("0647", "구로", 1, at=_at(12, 15))]                  # 구로 기준으로는 정시였지만
    g = build_gasan_board(gasan, live, set(), lambda n: guro, _at(12, 21, 30))[0]  # 아직 가산 도착 전
    assert g.delay_sec == 90 and g.remaining_sec == 0


def test_not_yet_running_train_uses_timetable():
    gasan = {647: _stop("K647", "12:20")}
    g = build_gasan_board(gasan, [], set(), lambda n: None, _at(12, 0))[0]
    assert g.live is None and g.expected == _at(12, 20) and g.delay_sec is None


def test_unseen_train_hidden_after_grace():
    gasan = {647: _stop("K647", "12:20")}
    assert build_gasan_board(gasan, [], set(), lambda n: None, _at(12, 21, 59))
    assert build_gasan_board(gasan, [], set(), lambda n: None, _at(12, 22, 1)) == []


def test_passed_train_hidden_and_excluded_destination():
    gasan = {647: _stop("K647", "12:20"), 449: _stop("K449", "12:24", dest="서동탄")}
    assert build_gasan_board(gasan, [], {647}, lambda n: None, _at(12, 10)) == []


def test_lookahead_and_order_and_max_rows():
    gasan = {n: _stop(f"K{n}", f"12:{n:02d}") for n in range(10, 60, 5)}
    gasan[999] = _stop("K999", "14:00")                                   # 60분 밖
    board = build_gasan_board(gasan, [], set(), lambda n: None, _at(12, 0))
    assert [g.train_no for g in board] == ["K10", "K15", "K20", "K25", "K30", "K35"][: cfg.SUBWAY_MAX_ROWS]


def test_at_station_first_and_live_without_timetable():
    gasan = {647: _stop("K647", "12:20")}
    live = [_live("0645", "가산디지털단지", 0, "0", at=_at(12, 9, 50)),       # 시간표에 없는 열차가 진입 중
            _live("0647", "구로", 1, at=_at(12, 9))]
    board = build_gasan_board(gasan, live, set(), lambda n: None, _at(12, 10))
    assert board[0].train_no == "0645" and board[0].at_station and board[0].remaining_sec == 0
    assert board[1].train_no == "K647" and board[1].delay_sec is None        # 구로 시간표 없음 → 지연 계산 불가
