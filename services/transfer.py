"""버스 → 1호선 환승 가능 여부 예상.

JNK디지털타워에서 버스를 타면 가산디지털단지역 승강장까지 BUS_TO_GASAN_MIN 분이 걸린다고 가정하고,
'버스 도착 + 이동 시간' 이 열차의 예상 도착보다 앞서는지 비교한다. 모든 시간은 조회 시점 기준(초).
"""
from __future__ import annotations

from enum import Enum

from config import settings as cfg
from models.bus import BusArrival, BusStatus
from models.subway import TrainPosition


class Catch(Enum):
    OK = "ok"        # 탑승 가능
    TIGHT = "tight"  # 아슬아슬 (버스·열차 도착 차이가 ±TRANSFER_TIGHT_SEC 이내)
    MISS = "miss"    # 탑승 어려움


def bus_arrival_sec(bus: BusArrival) -> int | None:
    """버스가 JNK디지털타워에 도착할 때까지 남은 시간. 알 수 없으면 None."""
    if bus.status == BusStatus.ARRIVING_SOON:
        return 0
    if bus.status == BusStatus.RUNNING and bus.remaining_sec is not None:
        return max(0, bus.remaining_sec)
    return None  # 출발대기·운행종료·정보없음


def judge(train: TrainPosition, bus: BusArrival) -> Catch | None:
    """해당 버스를 탔을 때 이 열차를 탈 수 있을지. 판단할 근거가 없으면 None."""
    bus_sec = bus_arrival_sec(bus)
    if bus_sec is None or train.stations_away is None:
        return None
    at_gasan = bus_sec + cfg.BUS_TO_GASAN_MIN * 60

    if train.stations_away == 0:
        train_sec = 0
    elif train.est_remaining_sec is not None:
        train_sec = train.est_remaining_sec
    else:
        # 소요시간 표보다 먼 열차: 최소한 표의 최대값만큼은 걸린다 → 그래도 여유가 있으면 가능
        far = max(cfg.SUBWAY_TRAVEL_MIN_BY_STATIONS)
        if train.stations_away <= far or train.age_sec is None:
            return None
        lower = cfg.SUBWAY_TRAVEL_MIN_BY_STATIONS[far] * 60 - train.age_sec
        return Catch.OK if lower - at_gasan >= cfg.TRANSFER_TIGHT_SEC else None

    slack = train_sec - at_gasan
    if slack >= cfg.TRANSFER_TIGHT_SEC:
        return Catch.OK
    if slack > -cfg.TRANSFER_TIGHT_SEC:
        return Catch.TIGHT
    return Catch.MISS
