from __future__ import annotations

import re

from dataclasses import dataclass, field
from datetime import datetime


@dataclass
class TrainPosition:
    """realtimePosition 의 열차 1대 (API 값 그대로 + 계산값)."""
    train_no: str             # trainNo
    subway_id: str            # subwayId (1001 = 1호선)
    updn_line: str            # updnLine (0 상행/내선, 1 하행/외선)
    station_id: str           # statnId  (현재 위치 역)
    station_name: str         # statnNm
    destination: str          # statnTnm (종착역)
    status_code: str          # trainSttus (0 진입, 1 도착, 2 출발, 3 전역출발)
    is_express: bool          # directAt == "1"
    is_last: bool             # lstcarAt == "1"
    generated_at: datetime | None  # recptnDt (위치 데이터 생성 시각)
    from_arrival_api: bool = False  # 위치 API 에 없어 역 도착정보 API 로 보충한 열차
    # --- 서비스 계층에서 채움 ---
    stations_away: int | None = None     # 가산디지털단지까지 남은 역 수
    age_sec: int | None = None           # 조회 시점 기준 데이터 경과 시간
    stale: bool = False
    destination_verified: bool = True

    @property
    def train_type(self) -> str:
        return "급행" if self.is_express else "일반"

    @property
    def status_text(self) -> str:
        word = {"0": "진입", "1": "도착", "2": "출발", "3": "전역출발"}.get(self.status_code, "")
        return f"{self.station_name} {word}".strip()


@dataclass
class SubwayInfo:
    station_name: str
    direction: str
    arrivals: list[GasanTrain]
    is_mock: bool = False
    warnings: list[str] = field(default_factory=list)


@dataclass
class GasanTrain:
    """가산디지털단지역 독산 방면 열차 1편 (시간표 API + 실시간 위치 API 를 열차번호로 합친 결과).

    시각은 모두 API 값에서만 나온다:
      scheduled = 시간표 API 의 가산 도착시각
      delay_sec = 실시간 위치 수신 시각 - 그 역의 시간표 시각 (시간표 API)
      expected  = scheduled + delay (지연이 음수면 0 으로 봄)
    """
    train_no: str
    destination: str
    is_express: bool
    scheduled: datetime | None            # 시간표상 가산 도착 (시간표에 없는 열차면 None)
    expected: datetime | None             # 지연 반영 예상 도착
    delay_sec: int | None                 # None = 실시간으로 지연을 계산하지 못함
    live: TrainPosition | None            # 실시간 위치 (없으면 아직 출발 전이거나 API 누락)
    remaining_sec: int | None = None      # 조회 시점 기준 남은 시간
    at_station: bool = False              # 가산에 진입/도착 중

    @property
    def train_type(self) -> str:
        return "급행" if self.is_express else "일반"

    @property
    def stations_away(self) -> int | None:
        return self.live.stations_away if self.live else None


def normalize_station_name(name: str) -> str:
    name = re.sub(r"\(.*?\)", "", name).strip()   # "쌍용(나사렛대)" → "쌍용"
    return name[:-1] if name.endswith("역") and len(name) > 2 else name
