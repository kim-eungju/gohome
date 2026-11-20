"""버스 → 1호선 환승 가능 여부 예상.

JNK디지털타워에서 버스를 타면 가산디지털단지역 승강장까지 BUS_TO_GASAN_MIN 분이 걸린다고 가정하고,
'버스 도착 + 이동 시간' 과 열차의 예상 도착(시간표 API + 실시간 지연)을 비교한다. 모든 시간은 조회 시점 기준(초).
"""
from __future__ import annotations

from enum import Enum

from config import settings as cfg
from models.bus import BusArrival, BusStatus
from models.subway import GasanTrain


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


def judge(train: GasanTrain, bus: BusArrival) -> Catch | None:
    """해당 버스를 탔을 때 이 열차를 탈 수 있을지. 열차·버스 시각을 모르면 None."""
    bus_sec = bus_arrival_sec(bus)
    train_sec = 0 if train.at_station else train.remaining_sec
    if bus_sec is None or train_sec is None:
        return None
    slack = train_sec - (bus_sec + cfg.BUS_TO_GASAN_MIN * 60)
    if slack >= cfg.TRANSFER_TIGHT_SEC:
        return Catch.OK
    if slack > -cfg.TRANSFER_TIGHT_SEC:
        return Catch.TIGHT
    return Catch.MISS
