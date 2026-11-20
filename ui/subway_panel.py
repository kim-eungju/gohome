from __future__ import annotations

from datetime import datetime

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (QFrame, QGridLayout, QHBoxLayout, QLabel, QScrollArea,
                               QVBoxLayout, QWidget)

from config import settings as cfg
from models.bus import BusArrival, BusInfo
from models.subway import GasanTrain, SubwayInfo
from services.transfer import Catch, judge
from ui.formatters import age_text, clear_layout, remaining_text

# 열 너비 (구분 / 행선지 / 예상 도착 / 현재 위치 / 정보 시각)
# 예상 도착(2)만 남는 폭을 모두 쓰고 나머지는 고정 폭 → 헤더와 모든 행의 열 경계가 정확히 맞는다.
_COL_FIXED = {0: 52, 1: 120, 3: 160, 4: 60}
_COL_ETA_MIN = 220
_BADGE_W = _COL_FIXED[0]
_SCROLLBAR_W = 8   # styles.qss 의 QScrollBar:vertical width
_BUS_NAME = {1: "첫 버스", 2: "둘째 버스"}
_CATCH_MARK = {Catch.OK: ("○", "ok"), Catch.TIGHT: ("△", "warn"), Catch.MISS: ("✕", "no")}


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
    for col in range(5):
        g.setColumnMinimumWidth(col, _COL_FIXED.get(col, _COL_ETA_MIN))
        g.setColumnStretch(col, 0 if col in _COL_FIXED else 1)
    return g


def _cell(col: int, content: QWidget | QHBoxLayout | QVBoxLayout) -> QWidget:
    """고정 폭 열은 내용과 상관없이 정확히 그 폭으로 만든다 (긴 글자는 줄바꿈)."""
    w = QWidget()
    if isinstance(content, QWidget):
        lay = QVBoxLayout(w)
        lay.addWidget(content)
    else:
        w.setLayout(content)
        lay = content
    lay.setContentsMargins(0, 0, 0, 0)
    if col in _COL_FIXED:
        w.setFixedWidth(_COL_FIXED[col])
    else:
        w.setMinimumWidth(_COL_ETA_MIN)
    return w


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
        # 행 = 스크롤 여백 8 + 행 여백 12, 오른쪽은 스크롤바 폭까지 더해 헤더와 맞춘다
        hg.setContentsMargins(20, 10, 20 + _SCROLLBAR_W, 6)
        for col, text in enumerate(("구분", "행선지", "예상 도착", "현재 위치", "정보 시각")):
            hg.addWidget(_cell(col, _label(text, "tableHead")), 0, col)
        outer.addWidget(head)

        self.scroll = QScrollArea()
        self.scroll.setWidgetResizable(True)
        self.scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.scroll.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOn)  # 스크롤바 유무로 열이 밀리지 않게
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
        ph = _label("도착정보를 불러오는 중입니다…", "placeholder")
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

    def show_info(self, info: SubwayInfo, queried_at: datetime, bus: BusInfo | None = None) -> None:
        self.mock_tag.setVisible(info.is_mock)
        if not info.arrivals:
            ph = _label("도착정보 없음", "subwayTimeMuted")
            ph.setAlignment(Qt.AlignCenter)
            self._set_body_message(ph)
        else:
            buses = [b for b in (bus.arrivals if bus else []) if b.order in _BUS_NAME]
            clear_layout(self.rows)
            for a in info.arrivals:
                self.rows.addWidget(self._row(a, queried_at, buses))
            self.rows.addStretch(1)

        notes = []
        if info.is_mock:
            notes.append("※ MOCK 모드 테스트 데이터입니다. 실제 도착정보가 아닙니다.")
        elif info.arrivals:
            notes.append("예상 도착 = 서울시 시간표 API 의 가산 도착시각 + 실시간 위치로 계산한 지연. "
                         "'실시간 없음' 열차는 아직 출발 전이거나 위치 API 에서 빠진 열차로, 시간표 시각 그대로입니다.")
            if any(a.live and a.live.stale for a in info.arrivals):
                notes.append("⚠ '정보 지연' 열차는 위치 정보가 5분 이상 갱신되지 않아 참고용입니다.")
        if info.arrivals and bus is not None:
            notes.append(f"버스 탑승 시 환승: JNK디지털타워 → 가산디지털단지역 {cfg.BUS_TO_GASAN_MIN}분 가정 "
                         f"(○ 가능 · △ 아슬아슬 · ✕ 어려움)")
        notes.extend(w for w in info.warnings if w not in notes)
        self.footer.setText("\n".join(notes))

    # ------------------------------------------------------------------
    def _row(self, a: GasanTrain, queried_at: datetime, buses: list[BusArrival]) -> QWidget:
        row = QFrame(objectName="subwayRow")
        g = _grid()
        row.setLayout(g)
        g.setContentsMargins(12, 10, 12, 10)

        badge = QLabel(a.train_type)
        badge.setProperty("badge", a.train_type)
        badge.setAlignment(Qt.AlignCenter)
        badge.setFixedWidth(_BADGE_W)
        g.addWidget(_cell(0, badge), 0, 0, Qt.AlignVCenter)

        live = a.live
        dest_box = QVBoxLayout()
        dest_box.setSpacing(2)
        dest_box.addWidget(_label(f"{a.destination}행" if a.destination else "행선지 미상", "destName", wrap=True))
        tags = QVBoxLayout()   # 태그가 여러 개면 세로로 쌓아 고정 폭을 넘지 않게
        tags.setSpacing(2)
        if live and live.is_last:
            tags.addWidget(_tag("막차"))
        if live and live.stale:
            tags.addWidget(_tag("정보 지연"))
        if live is None:
            tags.addWidget(_tag("실시간 없음", "info"))
        for i in range(tags.count()):
            tags.itemAt(i).setAlignment(Qt.AlignLeft)
        if tags.count():
            dest_box.addLayout(tags)
        g.addWidget(_cell(1, dest_box), 0, 1, Qt.AlignVCenter)

        box = QVBoxLayout()
        box.setSpacing(0)
        if a.at_station:
            box.addWidget(_label("진입 중" if live.status_code == "0" else "도착", "subwayTime"))
        elif a.remaining_sec is not None:
            box.addWidget(_label(remaining_text(a.remaining_sec), "subwayTime"))
            box.addWidget(_label(self._time_detail(a), "etaText", wrap=True))
        else:
            box.addWidget(_label("시간표 없음", "subwayTimeMuted"))
        catch = QHBoxLayout()
        catch.setSpacing(4)
        for b in buses:
            result = judge(a, b)
            if result is not None:
                mark, kind = _CATCH_MARK[result]
                catch.addWidget(_tag(f"{_BUS_NAME[b.order]} {mark}", kind))
        if catch.count():
            catch.addStretch(1)
            box.addSpacing(3)
            box.addLayout(catch)
        g.addWidget(_cell(2, box), 0, 2, Qt.AlignVCenter)

        if live is not None:
            where = live.status_text or "-"
            if live.stations_away:
                where += f" · {live.stations_away}역 전"
        else:
            where = "위치 정보 없음"
        g.addWidget(_cell(3, _label(where, "statusText", wrap=True)), 0, 3, Qt.AlignVCenter)
        g.addWidget(_cell(4, _label(age_text(live.age_sec) if live else "-", "etaText")), 0, 4)
        return row

    @staticmethod
    def _time_detail(a: GasanTrain) -> str:
        """'12:22 도착 예정 · 시간표 12:20 (+2분)' 형태."""
        hm = lambda d: d.strftime("%H:%M")
        text = f"{hm(a.expected)} 도착 예정"
        if a.scheduled is None:
            return text
        if a.live is None:
            return f"{hm(a.scheduled)} 시간표 기준"
        if a.delay_sec is None:
            return f"{text} · 지연 계산 불가"
        late_min = round(max(0, a.delay_sec) / 60)
        return f"{text} · 시간표 {hm(a.scheduled)}" + (f" (+{late_min}분)" if late_min else " (정시)")
