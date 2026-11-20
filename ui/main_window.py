from __future__ import annotations

import logging
from typing import Callable

from PySide6.QtCore import QObject, QRunnable, Qt, QThreadPool, QTimer, Signal, Slot
from PySide6.QtGui import QCloseEvent
from PySide6.QtWidgets import (QHBoxLayout, QLabel, QMainWindow, QProgressBar, QPushButton,
                               QVBoxLayout, QWidget)

from config.settings import Settings
from services.transit_service import QueryResult, TransitService
from ui.bus_panel import BusPanel
from ui.formatters import clock
from ui.subway_panel import SubwayPanel

log = logging.getLogger(__name__)

AUTO_REFRESH_MS = 10_000  # 자동 조회 간격 (10초)


class _Signals(QObject):
    done = Signal(object)


class _QueryTask(QRunnable):
    """조회를 백그라운드 스레드에서 1회 실행 (UI 멈춤 방지). 반복 실행하지 않는다."""

    def __init__(self, fn: Callable[[], QueryResult]):
        super().__init__()
        self.fn = fn
        self.signals = _Signals()

    def run(self) -> None:
        try:
            result: object = self.fn()
        except Exception as e:  # 서비스 내부에서 처리되지 않은 예외도 UI 로 전달
            log.exception("query failed")
            result = e
        self.signals.done.emit(result)


class MainWindow(QMainWindow):
    def __init__(self, service: TransitService, settings: Settings):
        super().__init__()
        self.service = service
        self.settings = settings
        self._task: _QueryTask | None = None
        self._closing = False

        # 자동 조회: 조회가 끝난 뒤 10초 후 다음 조회 (요청이 겹치지 않도록 singleShot)
        self._auto_timer = QTimer(self)
        self._auto_timer.setSingleShot(True)
        self._auto_timer.setInterval(AUTO_REFRESH_MS)
        self._auto_timer.timeout.connect(self.on_query)

        self.setWindowTitle("퇴근길 교통정보")
        self.resize(1000, 600)
        self.setMinimumSize(820, 480)

        root = QWidget(objectName="root")
        self.setCentralWidget(root)
        outer = QVBoxLayout(root)
        outer.setContentsMargins(24, 18, 24, 20)
        outer.setSpacing(12)

        # ---- 상단 ----
        top = QHBoxLayout()
        top.setSpacing(12)
        title = QLabel("퇴근길 교통정보", objectName="appTitle")
        top.addWidget(title)
        self.mock_banner = QLabel("MOCK 모드 · 테스트 데이터", objectName="mockBanner")
        self.mock_banner.setVisible(settings.mock_mode)
        top.addWidget(self.mock_banner)
        top.addStretch(1)
        self.last_query = QLabel("마지막 조회  -", objectName="lastQuery")
        top.addWidget(self.last_query)
        self.button = QPushButton("조회", objectName="queryButton")
        self.button.setCursor(Qt.PointingHandCursor)
        self.button.clicked.connect(self.on_query)
        top.addWidget(self.button)
        outer.addLayout(top)

        self.busy = QProgressBar(objectName="busy")
        self.busy.setRange(0, 0)
        self.busy.setTextVisible(False)
        self.busy.setFixedHeight(3)
        self.busy.setVisible(False)
        outer.addWidget(self.busy)

        self.notice = QLabel(objectName="notice")
        self.notice.setWordWrap(True)
        msg = settings.missing_key_message()
        self.notice.setText(msg or "")
        self.notice.setVisible(bool(msg))
        outer.addWidget(self.notice)

        # ---- 좌우 패널 ----
        panels = QHBoxLayout()
        panels.setSpacing(16)
        self.bus_panel = BusPanel()
        self.subway_panel = SubwayPanel()
        panels.addWidget(self.bus_panel, 2)
        panels.addWidget(self.subway_panel, 3)
        outer.addLayout(panels, 1)

        # 실행 직후 1회 조회 (이후 10초마다 자동 조회)
        QTimer.singleShot(0, self.on_query)

    def closeEvent(self, event: QCloseEvent) -> None:
        # 창을 닫으면 자동 조회를 확실히 멈춘다 (API 일일 호출 한도 보호)
        self._closing = True
        self._auto_timer.stop()
        log.info("window closed; auto refresh stopped")
        super().closeEvent(event)

    # ------------------------------------------------------------------
    @Slot()
    def on_query(self) -> None:
        if self._closing or self._task is not None:
            return
        self._auto_timer.stop()  # 수동 조회 시 10초 타이머를 다시 시작
        self.button.setEnabled(False)
        self.button.setText("조회 중…")
        self.busy.setVisible(True)
        self._task = _QueryTask(self.service.query)
        self._task.signals.done.connect(self._on_done)
        QThreadPool.globalInstance().start(self._task)

    @Slot(object)
    def _on_done(self, result: object) -> None:
        try:
            if isinstance(result, QueryResult):
                self._render(result)
            else:
                msg = "조회 중 알 수 없는 오류가 발생했습니다. 잠시 후 다시 시도해 주세요."
                self.bus_panel.show_error(msg)
                self.subway_panel.show_error(msg)
        except Exception:
            log.exception("render failed")
        finally:
            self._task = None
            self.busy.setVisible(False)
            self.button.setText("조회")
            self.button.setEnabled(True)
            if not self._closing:
                self._auto_timer.start()

    def _render(self, r: QueryResult) -> None:
        if r.bus is not None:
            self.bus_panel.show_info(r.bus, r.queried_at)
        else:
            self.bus_panel.show_error(r.bus_error or "알 수 없는 오류")
        if r.subway is not None:
            self.subway_panel.show_info(r.subway, r.queried_at, r.bus)
        else:
            self.subway_panel.show_error(r.subway_error or "알 수 없는 오류")
        suffix = "  (테스트 데이터)" if r.is_mock else ""
        self.last_query.setText(f"마지막 조회  {clock(r.queried_at)}{suffix}")
