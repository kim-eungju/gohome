from __future__ import annotations

from datetime import datetime

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (QFrame, QGridLayout, QHBoxLayout, QLabel, QScrollArea,
                               QVBoxLayout, QWidget)

from config import settings as cfg
from models.subway import SubwayInfo, TrainPosition
from ui.formatters import age_text, clear_layout, eta_text, remaining_text

# 열 너비 (구분 / 행선지 / 가산까지 / 현재 위치 / 정보 시각)
_COL_STRETCH = (0, 3, 3, 4, 0)
_BADGE_W = 52
_ETA_W = 64


def _label(text: str, name: str = "", wrap: bool = False) -> QLabel:
    lb = QLabel(text)
    if name:
        lb.setObjectName(name)
    lb.setWordWrap(wrap)
    return lb


def _tag(text: str, kind: str = "warn") -> QLabel:
    lb = QLabel(text)
    lb.setProperty("tag", kind)
    return lb


def _grid() -> QGridLayout:
    g = QGridLayout()
    g.setHorizontalSpacing(12)
    g.setColumnMinimumWidth(0, _BADGE_W)
    g.setColumnMinimumWidth(4, _ETA_W)
    for i, s in enumerate(_COL_STRETCH):
        g.setColumnStretch(i, s)
    return g


class SubwayPanel(QFrame):
    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        self.setObjectName("subwayCard")
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)

        header = QFrame(objectName="subwayHeader")
        h = QVBoxLayout(header)
        h.setContentsMargins(20, 16, 20, 14)
        h.setSpacing(6)
        top = QHBoxLayout()
        top.setSpacing(10)
        top.addWidget(_label("1호선", "line1Badge"))
        top.addWidget(_label(cfg.SUBWAY_STATION_NAME, "cardTitle"))
        top.addStretch(1)
        self.mock_tag = _label("테스트 데이터", "mockTag")
        self.mock_tag.hide()
        top.addWidget(self.mock_tag)
        h.addLayout(top)
        h.addWidget(_label(f"{cfg.SUBWAY_DIRECTION_LABEL} · 급행 포함", "cardSubtitle"))
        outer.addWidget(header)

        # 표 머리
        head = QWidget()
        hg = _grid()
        head.setLayout(hg)
        hg.setContentsMargins(20, 10, 20, 6)
        for col, text in enumerate(("구분", "행선지", "예상 도착", "현재 위치", "정보 시각")):
            hg.addWidget(_label(text, "tableHead"), 0, col)
        outer.addWidget(head)

        self.scroll = QScrollArea()
        self.scroll.setWidgetResizable(True)
        self.scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        container = QWidget()
        self.rows = QVBoxLayout(container)
        self.rows.setContentsMargins(8, 0, 8, 0)
        self.rows.setSpacing(0)
        self.scroll.setWidget(container)
        outer.addWidget(self.scroll, 1)

        self.footer = _label("", "cardFooter", wrap=True)
        self.footer.setContentsMargins(20, 8, 20, 14)
        outer.addWidget(self.footer)
        self.show_placeholder()

    # ------------------------------------------------------------------
    def _set_body_message(self, widget: QLabel) -> None:
        clear_layout(self.rows)
        self.rows.addSpacing(40)
        self.rows.addWidget(widget)
        self.rows.addStretch(1)

    def show_placeholder(self) -> None:
        ph = _label("조회 버튼을 눌러 도착정보를 확인하세요.", "placeholder")
        ph.setAlignment(Qt.AlignCenter)
        self._set_body_message(ph)
        self.footer.setText("")

    def show_error(self, message: str) -> None:
        self.mock_tag.hide()
        err = _label(f"지하철 정보를 불러오지 못했습니다.\n{message}", "cardError", wrap=True)
        clear_layout(self.rows)
        self.rows.addSpacing(12)
        self.rows.addWidget(err)
        self.rows.addStretch(1)
        self.footer.setText("")

    def show_info(self, info: SubwayInfo, queried_at: datetime) -> None:
        self.mock_tag.setVisible(info.is_mock)
        if not info.arrivals:
            ph = _label("도착정보 없음", "subwayTimeMuted")
            ph.setAlignment(Qt.AlignCenter)
            self._set_body_message(ph)
        else:
            clear_layout(self.rows)
            for a in info.arrivals:
                self.rows.addWidget(self._row(a, queried_at))
            self.rows.addStretch(1)

        notes = []
        if info.is_mock:
            notes.append("※ MOCK 모드 테스트 데이터입니다. 실제 도착정보가 아닙니다.")
        else:
            if info.arrivals:
                notes.append("예상 도착은 API 값이 아니라 역별 평소 소요시간(12역 이내)으로 계산한 추정치입니다. "
                             "'정보 시각'은 열차 위치가 확인된 시점입니다.")
            if any(a.stale for a in info.arrivals):
                notes.append("⚠ '정보 지연' 열차는 위치 정보가 5분 이상 갱신되지 않아 참고용입니다.")
        notes.extend(w for w in info.warnings if w not in notes)
        self.footer.setText("\n".join(notes))

    # ------------------------------------------------------------------
    def _row(self, a: TrainPosition, queried_at: datetime) -> QWidget:
        row = QFrame(objectName="subwayRow")
        g = _grid()
        row.setLayout(g)
        g.setContentsMargins(12, 10, 12, 10)

        kind = a.train_type
        badge = QLabel(a.train_type)
        badge.setProperty("badge", kind)
        badge.setAlignment(Qt.AlignCenter)
        badge.setFixedWidth(_BADGE_W)
        g.addWidget(badge, 0, 0, Qt.AlignVCenter)

        dest_box = QVBoxLayout()
        dest_box.setSpacing(2)
        dest_box.addWidget(_label(f"{a.destination}행" if a.destination else "행선지 미상", "destName"))
        tags = QHBoxLayout()
        tags.setSpacing(4)
        if a.is_last:
            tags.addWidget(_tag("막차"))
        if a.stale:
            tags.addWidget(_tag("정보 지연"))
        tags.addStretch(1)
        if tags.count() > 1:
            dest_box.addLayout(tags)
        g.addLayout(dest_box, 0, 1)

        box = QVBoxLayout()
        box.setSpacing(0)
        if a.stations_away == 0:
            box.addWidget(_label("진입 중" if a.status_code == "0" else "도착", "subwayTime"))
        elif a.est_remaining_sec is not None:
            box.addWidget(_label(remaining_text(a.est_remaining_sec), "subwayTime"))
            box.addWidget(_label(f"{a.stations_away}역 전 · {eta_text(queried_at, a.est_remaining_sec)} 예상",
                                 "etaText"))
        elif a.stations_away is not None:
            box.addWidget(_label(f"{a.stations_away}역 전", "subwayTimeMuted"))
        else:
            box.addWidget(_label("-", "subwayTimeMuted"))
        g.addLayout(box, 0, 2)
        g.addWidget(_label(a.status_text or "-", "statusText", wrap=True), 0, 3)
        g.addWidget(_label(age_text(a.age_sec), "etaText"), 0, 4)
        return row
