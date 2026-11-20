"""화면 표시용 문자열 변환 (UI 전용)."""
from __future__ import annotations

from datetime import datetime, timedelta


def remaining_text(sec: int | None) -> str:
    if sec is None:
        return "-"
    if sec < 60:
        return "곧 도착"
    return f"약 {(sec + 30) // 60}분"


def eta_text(base: datetime, sec: int | None) -> str:
    if sec is None:
        return ""
    return (base + timedelta(seconds=sec)).strftime("%H:%M")


def age_text(sec: int | None) -> str:
    if sec is None:
        return "시각 미상"
    if sec < 60:
        return "방금"
    return f"{sec // 60}분 전"


def clock(dt: datetime | None) -> str:
    return dt.strftime("%H:%M:%S") if dt else "-"


def clear_layout(layout) -> None:
    while layout.count():
        item = layout.takeAt(0)
        w = item.widget()
        if w is not None:
            w.deleteLater()
        elif item.layout() is not None:
            clear_layout(item.layout())
