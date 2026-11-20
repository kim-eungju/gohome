"""MOCK_MODE=true 일 때만 사용하는 테스트 데이터. 실제 API 모드에서는 절대 사용하지 않는다."""
from __future__ import annotations

from datetime import datetime, timedelta

from config import settings as cfg
from models.bus import BusArrival, BusInfo, BusStatus
from models.subway import GasanTrain, SubwayInfo, TrainPosition


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

    def live(station: str, away: int, status: str, age: int) -> TrainPosition:
        return TrainPosition(
            train_no="TEST", subway_id=cfg.SUBWAY_LINE_ID, updn_line="1", station_id="",
            station_name=station, destination="", status_code=status, is_express=False,
            is_last=False, generated_at=now - timedelta(seconds=age),
            stations_away=away, age_sec=age, stale=age > cfg.SUBWAY_STALE_AFTER_SEC,
        )

    def train(no: str, express: bool, dest: str, sched_min: float, delay_sec: int | None,
              pos: TrainPosition | None) -> GasanTrain:
        scheduled = (now + timedelta(minutes=sched_min)).replace(second=0, microsecond=0)
        expected = scheduled + timedelta(seconds=max(0, delay_sec or 0))
        g = GasanTrain(no, dest, express, scheduled, expected, delay_sec, pos)
        g.remaining_sec = max(0, int((expected - now).total_seconds()))
        return g

    trains = [
        train("K645", False, "신창", 3, 120, live("구로", 1, "1", 20)),
        train("K1919", True, "천안", 8, 420, live("영등포", 3, "2", 45)),
        train("K647", False, "신창", 19, None, None),
        train("K1921", True, "천안", 27, 60, live("서울", 9, "0", 15)),
        train("K649", False, "천안", 36, 0, live("종로5가", 13, "1", 400)),
    ]
    subway = SubwayInfo(cfg.SUBWAY_STATION_NAME, cfg.SUBWAY_DIRECTION_LABEL, trains, is_mock=True)
    return QueryResult(now, bus, None, subway, None, is_mock=True)
