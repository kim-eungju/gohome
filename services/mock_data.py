"""MOCK_MODE=true 일 때만 사용하는 테스트 데이터. 실제 API 모드에서는 절대 사용하지 않는다."""
from __future__ import annotations

from datetime import datetime, timedelta

from config import settings as cfg
from models.bus import BusArrival, BusInfo, BusStatus
from models.subway import SubwayInfo, TrainPosition


def build_mock_result(now: datetime):
    from services.transit_service import QueryResult

    bus = BusInfo(
        route_name=cfg.BUS_ROUTE_NAME,
        station_name=cfg.BUS_STATION_NAME,
        ars_id=cfg.BUS_STATION_ARS_ID,
        direction=cfg.BUS_DIRECTION_LABEL,
        arrivals=[
            BusArrival(1, BusStatus.RUNNING, 4 * 60 + 10, 2, "구로디지털단지역", "서울70사0000", False, "[테스트]"),
            BusArrival(2, BusStatus.RUNNING, 12 * 60 + 40, 7, "지타워.G밸리산업박물관", "서울70사0001", False, "[테스트]"),
        ],
        generated_at=now,
        is_mock=True,
    )

    def train(express: bool, dest: str, station: str, away: int, status: str, age: int) -> TrainPosition:
        return TrainPosition(
            train_no="TEST", subway_id=cfg.SUBWAY_LINE_ID, updn_line="1", station_id="",
            station_name=station, destination=dest, status_code=status, is_express=express,
            is_last=False, generated_at=now - timedelta(seconds=age),
            stations_away=away, age_sec=age,
        )

    trains = [
        train(False, "천안", "구로", 1, "1", 20),
        train(True, "신창", "영등포", 3, "2", 45),
        train(False, "신창", "노량진", 6, "1", 70),
        train(True, "천안", "서울역", 9, "0", 15),
        train(False, "천안", "시청", 10, "1", 400),
    ]
    trains[-1].stale = True
    from services.transit_service import estimate_remaining_sec
    for t in trains:
        t.est_remaining_sec = estimate_remaining_sec(t.stations_away, t.age_sec)
    subway = SubwayInfo(cfg.SUBWAY_STATION_NAME, cfg.SUBWAY_DIRECTION_LABEL, trains, is_mock=True)
    return QueryResult(now, bus, None, subway, None, is_mock=True)
