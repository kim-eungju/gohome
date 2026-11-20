from __future__ import annotations

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
    est_remaining_sec: int | None = None  # 예상 남은 시간 (소요시간 표 기반 추정, API 값 아님)
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
    arrivals: list[TrainPosition]
    is_mock: bool = False
    warnings: list[str] = field(default_factory=list)
