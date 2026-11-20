from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum


class BusStatus(Enum):
    RUNNING = "running"          # 도착 예정시간 있음
    ARRIVING_SOON = "soon"       # 곧 도착
    WAITING = "waiting"          # 출발대기 (기점 대기)
    ENDED = "ended"              # 운행종료
    NO_INFO = "no_info"          # 도착정보 없음


@dataclass
class BusArrival:
    order: int                     # 1 = 첫 번째 버스, 2 = 두 번째 버스
    status: BusStatus
    remaining_sec: int | None      # 조회 시점 기준 남은 시간(초). 없으면 None
    stops_away: int | None         # 남은 정류장 수
    current_stop: str | None       # 버스 현재 위치(정류장명)
    plate_no: str | None
    is_last: bool                  # 막차 여부
    raw_message: str               # API 원문 메시지 (arrmsg)


@dataclass
class BusInfo:
    route_name: str
    station_name: str
    ars_id: str
    direction: str
    arrivals: list[BusArrival]
    generated_at: datetime | None  # 데이터 생성 시각 (mkTm)
    stale: bool = False
    is_mock: bool = False
    warnings: list[str] = field(default_factory=list)
