"""gohome - 퇴근길 교통정보 (금천07 @ JNK디지털타워 / 1호선 가산디지털단지역 독산 방면)."""
from __future__ import annotations

import logging
import sys
from logging.handlers import RotatingFileHandler

from PySide6.QtCore import Qt
from PySide6.QtGui import QFont, QGuiApplication, QIcon
from PySide6.QtWidgets import QApplication, QMessageBox

from config.settings import app_dir, load_settings, resource_path
from services.transit_service import TransitService
from ui.main_window import MainWindow


class _MaskSecrets(logging.Filter):
    """로그에 API KEY 가 섞여 들어가도 마스킹."""

    def __init__(self, secrets: list[str]):
        super().__init__()
        self.secrets = [s for s in secrets if len(s) >= 6]

    def filter(self, record: logging.LogRecord) -> bool:
        if self.secrets:
            msg = record.getMessage()
            for s in self.secrets:
                msg = msg.replace(s, "****")
            record.msg, record.args = msg, None
        return True


def _setup_logging(secrets: list[str]) -> None:
    root = logging.getLogger()
    root.setLevel(logging.INFO)
    fmt = logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s")
    handlers: list[logging.Handler] = []
    try:
        handlers.append(RotatingFileHandler(app_dir() / "gohome.log", maxBytes=512_000,
                                            backupCount=1, encoding="utf-8"))
    except OSError:
        pass
    if sys.stderr is not None:  # --windowed EXE 에서는 stderr 가 없음
        handlers.append(logging.StreamHandler())
    mask = _MaskSecrets(secrets)
    for h in handlers:
        h.setFormatter(fmt)
        h.addFilter(mask)
        root.addHandler(h)
    # urllib3 는 요청 URL(인증키 포함)을 DEBUG 로 남기므로 레벨을 올려둔다
    logging.getLogger("urllib3").setLevel(logging.WARNING)


def main() -> int:
    settings = load_settings()
    _setup_logging(settings.secrets)
    log = logging.getLogger("gohome")
    log.info("start (mock=%s, env=%s)", settings.mock_mode, settings.env_path)

    QGuiApplication.setHighDpiScaleFactorRoundingPolicy(Qt.HighDpiScaleFactorRoundingPolicy.PassThrough)
    app = QApplication(sys.argv)
    app.setApplicationName("gohome")
    app.setFont(QFont("Malgun Gothic", 10))
    icon_path = resource_path("assets/gohome.ico")
    if icon_path.is_file():
        app.setWindowIcon(QIcon(str(icon_path)))
    try:
        app.setStyleSheet(resource_path("ui/styles.qss").read_text(encoding="utf-8"))
    except OSError:
        log.warning("styles.qss not found; using default style")

    def excepthook(exc_type, exc, tb):  # 예기치 못한 오류로 프로그램이 종료되지 않도록
        log.error("unhandled error", exc_info=(exc_type, exc, tb))
        QMessageBox.warning(None, "오류", "예기치 못한 오류가 발생했습니다.\n다시 조회해 주세요.")

    sys.excepthook = excepthook

    window = MainWindow(TransitService(settings), settings)
    window.show()
    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
