"""assets/gohome.ico 생성 (집 모양 아이콘). 실행: .venv\\Scripts\\python tools\\make_icon.py

여러 크기(16~256)의 PNG 를 하나의 .ico 에 담는다 (Windows Vista+ 의 PNG 기반 ICO).
"""
from __future__ import annotations

import struct
import sys
from pathlib import Path

from PySide6.QtCore import QBuffer, QByteArray, QIODevice, QPointF, QRectF, Qt
from PySide6.QtGui import QColor, QGuiApplication, QImage, QLinearGradient, QPainter, QPainterPath, QPen

SIZES = (16, 24, 32, 48, 64, 128, 256)
OUT = Path(__file__).resolve().parent.parent / "assets" / "gohome.ico"


def draw(size: int) -> QImage:
    img = QImage(size, size, QImage.Format_ARGB32)
    img.fill(Qt.transparent)
    p = QPainter(img)
    p.setRenderHint(QPainter.Antialiasing)
    p.scale(size / 256, size / 256)

    # 배경: 둥근 사각형 (파란 그라데이션)
    bg = QLinearGradient(0, 0, 0, 256)
    bg.setColorAt(0, QColor("#3B82F6"))
    bg.setColorAt(1, QColor("#1D4ED8"))
    p.setPen(Qt.NoPen)
    p.setBrush(bg)
    p.drawRoundedRect(QRectF(8, 8, 240, 240), 56, 56)

    white = QColor("#FFFFFF")
    # 지붕
    roof = QPainterPath()
    roof.moveTo(128, 46)
    roof.lineTo(218, 126)
    roof.lineTo(38, 126)
    roof.closeSubpath()
    pen = QPen(white, 18, Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin)
    p.setPen(pen)
    p.setBrush(white)
    p.drawPath(roof)
    # 굴뚝
    p.setPen(Qt.NoPen)
    p.drawRoundedRect(QRectF(164, 58, 24, 48), 4, 4)
    # 몸체
    p.drawRoundedRect(QRectF(62, 116, 132, 96), 10, 10)
    # 문 (따뜻한 주황색 = 불 켜진 집)
    p.setBrush(QColor("#F59E0B"))
    p.drawRoundedRect(QRectF(108, 146, 40, 66), 8, 8)
    p.setBrush(QColor("#1D4ED8"))
    p.drawEllipse(QPointF(139, 181), 4, 4)
    p.end()
    return img


def png_bytes(img: QImage) -> bytes:
    ba = QByteArray()
    buf = QBuffer(ba)
    buf.open(QIODevice.WriteOnly)
    img.save(buf, "PNG")
    return bytes(ba)


def from_image(path: Path):
    """원본 이미지를 정사각형으로 맞춰 각 크기로 고품질 축소."""
    src = QImage(str(path)).convertToFormat(QImage.Format_ARGB32)
    if src.isNull():
        raise SystemExit(f"이미지를 열 수 없습니다: {path}")
    side = max(src.width(), src.height())
    square = QImage(side, side, QImage.Format_ARGB32)
    square.fill(Qt.transparent)
    p = QPainter(square)
    p.drawImage((side - src.width()) // 2, (side - src.height()) // 2, src)
    p.end()
    return lambda s: square.scaled(s, s, Qt.KeepAspectRatio, Qt.SmoothTransformation)


def main() -> None:
    """인자 없이 실행하면 집 모양 아이콘, 이미지 경로를 주면 그 이미지로 아이콘 생성."""
    QGuiApplication(sys.argv)
    render = from_image(Path(sys.argv[1])) if len(sys.argv) > 1 else draw
    pngs = [(s, png_bytes(render(s))) for s in SIZES]
    header = struct.pack("<HHH", 0, 1, len(pngs))
    offset = 6 + 16 * len(pngs)
    entries, data = b"", b""
    for s, png in pngs:
        dim = 0 if s >= 256 else s
        entries += struct.pack("<BBBBHHII", dim, dim, 0, 0, 1, 32, len(png), offset + len(data))
        data += png
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_bytes(header + entries + data)
    render(256).save(str(OUT.with_suffix(".png")))
    print("saved", OUT)


if __name__ == "__main__":
    main()
