from __future__ import annotations

from datetime import datetime

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QFrame, QHBoxLayout, QLabel, QVBoxLayout, QWidget

from config import settings as cfg
from models.bus import BusArrival, BusInfo, BusStatus
from ui.formatters import clear_layout, clock, eta_text, remaining_text

_ORDINAL = {1: "첫 번째 버스", 2: "두 번째 버스"}


def _label(text: str, name: str, wrap: bool = False) -> QLabel:
    lb = QLabel(text)
    lb.setObjectName(name)
    lb.setWordWrap(wrap)
    return lb


def _tag(text: str, kind: str = "warn") -> QLabel:
    lb = QLabel(text)
    lb.setProperty("tag", kind)
    return lb


class BusPanel(QFrame):
    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        self.setObjectName("busCard")
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)

        header = QFrame(objectName="busHeader")
        h = QVBoxLayout(header)
        h.setContentsMargins(20, 16, 20, 14)
        h.setSpacing(6)
        top = QHBoxLayout()
        top.setSpacing(10)
        top.addWidget(_label(cfg.BUS_ROUTE_NAME, "busRouteBadge"))
        self.title = _label(cfg.BUS_STATION_NAME, "cardTitle")
        top.addWidget(self.title)
        top.addStretch(1)
        self.mock_tag = _label("테스트 데이터", "mockTag")
        self.mock_tag.hide()
        top.addWidget(self.mock_tag)
        h.addLayout(top)
        self.subtitle = _label(f"정류장 {cfg.BUS_STATION_ARS_ID} · {cfg.BUS_DIRECTION_LABEL}", "cardSubtitle")
        h.addWidget(self.subtitle)
        outer.addWidget(header)

        body = QWidget()
        self.body = QVBoxLayout(body)
        self.body.setContentsMargins(16, 16, 16, 8)
        self.body.setSpacing(12)
        outer.addWidget(body, 1)

        self.footer = _label("", "cardFooter", wrap=True)
        self.footer.setContentsMargins(20, 0, 20, 14)
        outer.addWidget(self.footer)
        self.show_placeholder()

    # ------------------------------------------------------------------
    def show_placeholder(self) -> None:
        clear_layout(self.body)
        ph = _label("조회 버튼을 눌러 도착정보를 확인하세요.", "placeholder")
        ph.setAlignment(Qt.AlignCenter)
        self.body.addStretch(1)
        self.body.addWidget(ph)
        self.body.addStretch(1)
        self.footer.setText("")

    def show_error(self, message: str) -> None:
        clear_layout(self.body)
        self.mock_tag.hide()
        err = _label(f"버스 정보를 불러오지 못했습니다.\n{message}", "cardError", wrap=True)
        self.body.addWidget(err)
        self.body.addStretch(1)
        self.footer.setText("")

    def show_info(self, info: BusInfo, queried_at: datetime) -> None:
        clear_layout(self.body)
        self.mock_tag.setVisible(info.is_mock)
        self.title.setText(info.station_name)
        self.subtitle.setText(f"정류장 {info.ars_id} · {info.direction}")

        if not info.arrivals:
            ph = _label("도착정보 없음", "busTimeMuted")
            ph.setAlignment(Qt.AlignCenter)
            self.body.addStretch(1)
            self.body.addWidget(ph)
            self.body.addStretch(1)
        else:
            for a in info.arrivals:
                self.body.addWidget(self._row(a, queried_at))
            self.body.addStretch(1)

        notes = []
        if info.is_mock:
            notes.append("※ MOCK 모드 테스트 데이터입니다. 실제 도착정보가 아닙니다.")
        elif info.generated_at:
            notes.append(f"데이터 생성 {clock(info.generated_at)}")
        if info.stale and not info.is_mock:
            notes.append("⚠ 갱신 지연 - 남은 시간은 참고용입니다.")
        notes.extend(info.warnings)
        self.footer.setText("\n".join(notes))
        self.footer.setObjectName("cardWarning" if (info.stale or info.warnings) and not info.is_mock else "cardFooter")
        self.footer.style().unpolish(self.footer)
        self.footer.style().polish(self.footer)

    # ------------------------------------------------------------------
    def _row(self, a: BusArrival, queried_at: datetime) -> QFrame:
        row = QFrame(objectName="busRow")
        lay = QVBoxLayout(row)
        lay.setContentsMargins(18, 12, 18, 12)
        lay.setSpacing(2)

        top = QHBoxLayout()
        top.addWidget(_label(_ORDINAL.get(a.order, f"{a.order}번째 버스"), "rowCaption"))
        top.addStretch(1)
        if a.is_last:
            top.addWidget(_tag("막차"))
        lay.addLayout(top)

        if a.status == BusStatus.RUNNING:
            text = remaining_text(a.remaining_sec)
            time_text, name = (text if text == "곧 도착" else f"{text} 후"), "busTime"
        elif a.status == BusStatus.ARRIVING_SOON:
            time_text, name = "곧 도착", "busTime"
        elif a.status == BusStatus.WAITING:
            time_text, name = "출발대기", "busTimeMuted"
        elif a.status == BusStatus.ENDED:
            time_text, name = "운행종료", "busTimeMuted"
        else:
            time_text, name = "도착정보 없음", "busTimeMuted"
        lay.addWidget(_label(time_text, name))

        details = []
        if a.stops_away is not None and a.status in (BusStatus.RUNNING, BusStatus.ARRIVING_SOON):
            details.append("직전 구간" if a.stops_away == 0 else f"{a.stops_away}정류장 전")
        if a.current_stop and a.status in (BusStatus.RUNNING, BusStatus.ARRIVING_SOON):
            details.append(f"현재 {a.current_stop}")
        eta = eta_text(queried_at, a.remaining_sec) if a.status == BusStatus.RUNNING else ""
        if eta:
            details.append(f"{eta} 도착 예정")
        if a.status == BusStatus.NO_INFO and a.raw_message:
            details.append(a.raw_message)
        if details:
            lay.addWidget(_label(" · ".join(details), "rowDetail", wrap=True))
        return row
